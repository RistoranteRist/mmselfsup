# Copyright (c) OpenMMLab. All rights reserved.
from typing import Dict, List, Tuple

import torch

from mmselfsup.core import SelfSupDataSample
from mmselfsup.registry import MODELS
from ..utils import GatherLayer
from .base import BaseModel


@MODELS.register_module()
class SimCLR(BaseModel):
    """SimCLR.

    Implementation of `A Simple Framework for Contrastive Learning of Visual
    Representations <https://arxiv.org/abs/2002.05709>`_.
    """

    @staticmethod
    def _create_buffer(
            batch_size: int
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Compute the mask and the index of positive samples.

        Args:
            batch_size (int): The batch size.

        Returns:
            Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
            - The mask for feature selection.
            - The index of positive samples.
            - The mask of negative samples.
        """
        mask = 1 - torch.eye(batch_size * 2, dtype=torch.uint8).cuda()
        pos_idx = (
            torch.arange(batch_size * 2).cuda(),
            2 * torch.arange(batch_size, dtype=torch.long).unsqueeze(1).repeat(
                1, 2).view(-1, 1).squeeze().cuda())
        neg_mask = torch.ones((batch_size * 2, batch_size * 2 - 1),
                              dtype=torch.uint8).cuda()
        neg_mask[pos_idx] = 0
        return mask, pos_idx, neg_mask

    def extract_feat(self, batch_inputs: List[torch.Tensor],
                     **kwargs) -> Tuple[torch.Tensor]:
        """Function to extract features from backbone.

        Args:
            batch_inputs (List[torch.Tensor]): The input images.

        Returns:
            Tuple[torch.Tensor]: Backbone outputs.
        """
        x = self.backbone(batch_inputs[0])
        return x

    def loss(self, batch_inputs: List[torch.Tensor],
             data_samples: List[SelfSupDataSample],
             **kwargs) -> Dict[str, torch.Tensor]:
        """Forward computation during training.

        Args:
            batch_inputs (List[torch.Tensor]): The input images.
            data_samples (List[SelfSupDataSample]): All elements required
                during the forward function.

        Returns:
            Dict[str, torch.Tensor]: A dictionary of loss components.
        """
        assert isinstance(batch_inputs, list)
        inputs = torch.stack(batch_inputs, 1)
        inputs = inputs.reshape((inputs.size(0) * 2, inputs.size(2),
                                 inputs.size(3), inputs.size(4)))
        x = self.backbone(inputs)
        z = self.neck(x)[0]  # (2n)xd

        z = z / (torch.norm(z, p=2, dim=1, keepdim=True) + 1e-10)
        z = torch.cat(GatherLayer.apply(z), dim=0)  # (2N)xd
        assert z.size(0) % 2 == 0
        N = z.size(0) // 2
        s = torch.matmul(z, z.permute(1, 0))  # (2N)x(2N)
        mask, pos_idx, neg_mask = self._create_buffer(N)

        # remove diagonal, (2N)x(2N-1)
        s = torch.masked_select(s, mask == 1).reshape(s.size(0), -1)
        positive = s[pos_idx].unsqueeze(1)  # (2N)x1

        # select negative, (2N)x(2N-2)
        negative = torch.masked_select(s, neg_mask == 1).reshape(s.size(0), -1)

        loss = self.head(positive, negative)
        losses = dict(loss=loss)
        return losses
