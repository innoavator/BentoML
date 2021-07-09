from bentoml.frameworks.coreml import CoreMLModelArtifact
from bentoml.frameworks.detectron import DetectronModelArtifact
from bentoml.frameworks.easyocr import EasyOCRArtifact
from bentoml.frameworks.evalml import EvalMLModelArtifact
from bentoml.frameworks.fastai import FastaiModelArtifact, Fastai1ModelArtifact
from bentoml.frameworks.fasttext import FasttextModelArtifact
from bentoml.frameworks.gluon import GluonModelArtifact
from bentoml.frameworks.h2o import H2oModelArtifact
from bentoml.frameworks.keras import KerasModelArtifact
from bentoml.frameworks.lightgbm import LightGBMModelArtifact
from bentoml.frameworks.onnx import OnnxModelArtifact
from bentoml.frameworks.onnxmlir import OnnxMlirModelArtifact
from bentoml.frameworks.paddle import PaddlePaddleModelArtifact
from bentoml.frameworks.pytorch import PytorchModelArtifact, PytorchLightningModelArtifact
from bentoml.frameworks.sklearn import SklearnModelArtifact
from bentoml.frameworks.spacy import SpacyModelArtifact
from bentoml.frameworks.tensorflow import TensorflowSavedModelArtifact
from bentoml.frameworks.transformers import TransformersModelArtifact
from bentoml.frameworks.xgboost import XgboostModelArtifact

__all__ = [
    "CoreMLModelArtifact",
    "DetectronModelArtifact",
    "EasyOCRArtifact",
    "EvalMLModelArtifact",
    "FastaiModelArtifact",
    "Fastai1ModelArtifact",
    "FasttextModelArtifact",
    "GluonModelArtifact",
    "H2oModelArtifact",
    "KerasModelArtifact",
    "LightGBMModelArtifact",
    "OnnxModelArtifact",
    "OnnxMlirModelArtifact",
    "PaddlePaddleModelArtifact",
    "PytorchModelArtifact",
    "PytorchLightningModelArtifact",
    "SklearnModelArtifact",
    "SpacyModelArtifact",
    "TensorflowSavedModelArtifact",
    "TransformersModelArtifact",
    "XgboostModelArtifact",
]
