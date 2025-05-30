# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""ReforesTree dataset."""

import glob
import os
from collections.abc import Callable

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from matplotlib.figure import Figure
from PIL import Image
from torch import Tensor

from .errors import DatasetNotFoundError
from .geo import NonGeoDataset
from .utils import Path, check_integrity, download_and_extract_archive, extract_archive


class ReforesTree(NonGeoDataset):
    """ReforesTree dataset.

    The `ReforesTree <https://github.com/gyrrei/ReforesTree>`__
    dataset contains drone imagery that can be used for tree crown detection,
    tree species classification and Aboveground Biomass (AGB) estimation.

    Dataset features:

    * 100 high resolution RGB drone images at 2 cm/pixel of size 4,000 x 4,000 px
    * more than 4,600 tree crown box annotations
    * tree crown matched with field measurements of diameter at breast height (DBH),
      and computed AGB and carbon values

    Dataset format:

    * images are three-channel pngs
    * annotations are csv file

    Dataset Classes:

    0. other
    1. banana
    2. cacao
    3. citrus
    4. fruit
    5. timber

    If you use this dataset in your research, please cite the following paper:

    * https://arxiv.org/abs/2201.11192

    .. versionadded:: 0.3
    """

    classes = ('other', 'banana', 'cacao', 'citrus', 'fruit', 'timber')
    url = 'https://zenodo.org/records/6813783/files/reforesTree.zip?download=1'

    md5 = 'f6a4a1d8207aeaa5fbab7b21b683a302'
    zipfilename = 'reforesTree.zip'

    def __init__(
        self,
        root: Path = 'data',
        transforms: Callable[[dict[str, Tensor]], dict[str, Tensor]] | None = None,
        download: bool = False,
        checksum: bool = False,
    ) -> None:
        """Initialize a new ReforesTree dataset instance.

        Args:
            root: root directory where dataset can be found
            transforms: a function/transform that takes input sample and its target as
                entry and returns a transformed version
            download: if True, download dataset and store it in the root directory
            checksum: if True, check the MD5 of the downloaded files (may be slow)

        Raises:
            DatasetNotFoundError: If dataset is not found and *download* is False.
        """
        self.root = root
        self.transforms = transforms
        self.checksum = checksum
        self.download = download

        self._verify()

        self.files = self._load_files(self.root)

        self.annot_df = pd.read_csv(os.path.join(root, 'mapping', 'final_dataset.csv'))

        self.class2idx: dict[str, int] = {c: i for i, c in enumerate(self.classes)}

    def __getitem__(self, index: int) -> dict[str, Tensor]:
        """Return an index within the dataset.

        Args:
            index: index to return

        Returns:
            data and label at that index
        """
        filepath = self.files[index]

        image = self._load_image(filepath)

        boxes, labels, agb = self._load_target(filepath)

        sample = {'image': image, 'bbox_xyxy': boxes, 'label': labels, 'agb': agb}

        if self.transforms is not None:
            sample = self.transforms(sample)

        return sample

    def __len__(self) -> int:
        """Return the number of data points in the dataset.

        Returns:
            length of the dataset
        """
        return len(self.files)

    def _load_files(self, root: Path) -> list[str]:
        """Return the paths of the files in the dataset.

        Args:
            root: root dir of dataset

        Returns:
            list of dicts containing paths for each pair of image, annotation
        """
        image_paths = sorted(glob.glob(os.path.join(root, 'tiles', '**', '*.png')))

        # https://github.com/gyrrei/ReforesTree/issues/6
        bad_paths = [
            'Carlos Vera Guevara RGB_15_8425_8305_12425_12305.png',
            'Flora Pluas RGB_3_0_11400_4000_15400.png',
            'Flora Pluas RGB_4_0_11578_4000_15578.png',
            'Flora Pluas RGB_23_12782_11400_16782_15400.png',
            'Flora Pluas RGB_24_12782_11578_16782_15578.png',
        ]
        final_paths = []
        for path in image_paths:
            if os.path.basename(path) not in bad_paths:
                final_paths.append(path)

        return final_paths

    def _load_image(self, path: Path) -> Tensor:
        """Load a single image.

        Args:
            path: path to the image

        Returns:
            the image
        """
        with Image.open(path) as img:
            array: np.typing.NDArray[np.uint8] = np.array(img)
            tensor = torch.from_numpy(array).float()
            # Convert from HxWxC to CxHxW
            tensor = tensor.permute((2, 0, 1))
            return tensor

    def _load_target(self, filepath: Path) -> tuple[Tensor, ...]:
        """Load boxes and labels for a single image.

        Args:
            filepath: image tile filepath

        Returns:
            dictionary containing boxes, label, and agb value
        """
        tile_df = self.annot_df[self.annot_df['img_path'] == os.path.basename(filepath)]

        boxes = torch.Tensor(tile_df[['xmin', 'ymin', 'xmax', 'ymax']].values.tolist())
        labels = torch.Tensor(
            [self.class2idx[label] for label in tile_df['group'].tolist()]
        ).long()
        agb = torch.Tensor(tile_df['AGB'].tolist())

        return boxes, labels, agb

    def _verify(self) -> None:
        """Checks the integrity of the dataset structure."""
        filepaths = [os.path.join(self.root, dir) for dir in ['tiles', 'mapping']]
        if all([os.path.exists(filepath) for filepath in filepaths]):
            return

        filepath = os.path.join(self.root, self.zipfilename)
        if os.path.isfile(filepath):
            if self.checksum and not check_integrity(filepath, self.md5):
                raise RuntimeError('Dataset found, but corrupted.')
            extract_archive(filepath)
            return

        # Check if the user requested to download the dataset
        if not self.download:
            raise DatasetNotFoundError(self)

        # else download the dataset
        self._download()

    def _download(self) -> None:
        """Download the dataset and extract it."""
        download_and_extract_archive(
            self.url,
            self.root,
            filename=self.zipfilename,
            md5=self.md5 if self.checksum else None,
        )

    def plot(
        self,
        sample: dict[str, Tensor],
        show_titles: bool = True,
        suptitle: str | None = None,
    ) -> Figure:
        """Plot a sample from the dataset.

        Args:
            sample: a sample returned by :meth:`__getitem__`
            show_titles: flag indicating whether to show titles above each panel
            suptitle: optional string to use as a suptitle

        Returns:
            a matplotlib Figure with the rendered sample
        """
        image = sample['image'].permute((1, 2, 0)).numpy()
        ncols = 1
        showing_predictions = 'prediction_bbox_xyxy' in sample
        if showing_predictions:
            ncols += 1

        fig, axs = plt.subplots(ncols=ncols, figsize=(ncols * 10, 10))
        if not showing_predictions:
            axs = [axs]

        axs[0].imshow(image)
        axs[0].axis('off')

        bboxes = [
            patches.Rectangle(
                (bbox[0], bbox[1]),
                bbox[2] - bbox[0],
                bbox[3] - bbox[1],
                linewidth=1,
                edgecolor='r',
                facecolor='none',
            )
            for bbox in sample['bbox_xyxy'].numpy()
        ]
        for bbox in bboxes:
            axs[0].add_patch(bbox)

        if show_titles:
            axs[0].set_title('Ground Truth')

        if showing_predictions:
            axs[1].imshow(image)
            axs[1].axis('off')

            pred_bboxes = [
                patches.Rectangle(
                    (bbox[0], bbox[1]),
                    bbox[2] - bbox[0],
                    bbox[3] - bbox[1],
                    linewidth=1,
                    edgecolor='r',
                    facecolor='none',
                )
                for bbox in sample['prediction_bbox_xyxy'].numpy()
            ]
            for bbox in pred_bboxes:
                axs[1].add_patch(bbox)

            if show_titles:
                axs[1].set_title('Predictions')

        if suptitle is not None:
            plt.suptitle(suptitle)

        return fig
