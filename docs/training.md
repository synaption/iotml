# Training AI Models for Edge Deployment

This guide covers how to train machine-learning models that are suitable for edge inference: small, fast, and portable.

---

## Table of Contents

- [Choosing a Framework](#choosing-a-framework)
- [Preparing Your Dataset](#preparing-your-dataset)
- [Training a Model](#training-a-model)
  - [TensorFlow / Keras](#tensorflow--keras)
  - [PyTorch](#pytorch)
- [Evaluating the Model](#evaluating-the-model)
- [Exporting for Edge Inference](#exporting-for-edge-inference)
  - [TensorFlow Lite](#tensorflow-lite)
  - [ONNX](#onnx)
- [Quantization and Optimization](#quantization-and-optimization)
- [Next Steps](#next-steps)

---

## Choosing a Framework

| Scenario | Recommended framework | Export format |
|----------|-----------------------|---------------|
| Image classification / object detection | TensorFlow / Keras | TensorFlow Lite |
| Custom research architectures | PyTorch | ONNX |
| Real-time audio / sensor data | Either | ONNX or TFLite |

---

## Preparing Your Dataset

1. **Collect raw data** from your IoT sensors, cameras, or data feeds.
2. **Label** the data using a tool such as [Label Studio](https://labelstud.io/) or [Roboflow](https://roboflow.com/).
3. **Split** into training, validation, and test sets (e.g. 70 / 15 / 15).
4. **Normalize** inputs to the range the model expects (typically `[0, 1]` or `[-1, 1]`).

```
dataset/
├── train/
│   ├── class_a/
│   └── class_b/
├── val/
│   ├── class_a/
│   └── class_b/
└── test/
    ├── class_a/
    └── class_b/
```

---

## Training a Model

### TensorFlow / Keras

```python
import tensorflow as tf
from tensorflow import keras

# Load data
train_ds = keras.utils.image_dataset_from_directory(
    "dataset/train", image_size=(224, 224), batch_size=32
)
val_ds = keras.utils.image_dataset_from_directory(
    "dataset/val", image_size=(224, 224), batch_size=32
)

# Build model (MobileNetV2 is a good edge-friendly baseline)
base_model = keras.applications.MobileNetV2(
    input_shape=(224, 224, 3), include_top=False, weights="imagenet"
)
base_model.trainable = False

model = keras.Sequential([
    base_model,
    keras.layers.GlobalAveragePooling2D(),
    keras.layers.Dense(2, activation="softmax"),
])

model.compile(
    optimizer="adam",
    loss="sparse_categorical_crossentropy",
    metrics=["accuracy"],
)

model.fit(train_ds, validation_data=val_ds, epochs=10)
model.save("saved_model/")
```

### PyTorch

```python
import torch
import torch.nn as nn
import torchvision.models as models
from torchvision import datasets, transforms
from torch.utils.data import DataLoader

transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])

train_dataset = datasets.ImageFolder("dataset/train", transform=transform)
train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)

model = models.mobilenet_v2(weights="IMAGENET1K_V1")
model.classifier[1] = nn.Linear(model.last_channel, 2)

criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

for epoch in range(10):
    model.train()
    for images, labels in train_loader:
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

torch.save(model.state_dict(), "model.pth")
```

---

## Evaluating the Model

Always evaluate on the held-out **test set** before exporting.

```python
# TensorFlow
loss, accuracy = model.evaluate(test_ds)
print(f"Test accuracy: {accuracy:.2%}")
```

Key metrics to track:

| Metric | Why it matters on edge |
|--------|------------------------|
| Accuracy / F1 | Basic correctness |
| Latency (ms) | Must fit real-time SLA |
| Model size (MB) | Constrained storage on edge nodes |
| Peak RAM usage (MB) | Constrained RAM on edge nodes |

---

## Exporting for Edge Inference

### TensorFlow Lite

```python
import tensorflow as tf

# Convert from SavedModel
converter = tf.lite.TFLiteConverter.from_saved_model("saved_model/")
tflite_model = converter.convert()

with open("model.tflite", "wb") as f:
    f.write(tflite_model)
```

### ONNX

```python
# PyTorch → ONNX
import torch

model.eval()
dummy_input = torch.randn(1, 3, 224, 224)
torch.onnx.export(
    model,
    dummy_input,
    "model.onnx",
    input_names=["input"],
    output_names=["output"],
    dynamic_axes={"input": {0: "batch_size"}, "output": {0: "batch_size"}},
    opset_version=17,
)
```

---

## Quantization and Optimization

Quantization reduces model size (often 4×) and improves inference speed at the cost of a small accuracy drop.

**TFLite post-training integer quantization:**

```python
converter = tf.lite.TFLiteConverter.from_saved_model("saved_model/")
converter.optimizations = [tf.lite.Optimize.DEFAULT]

# Provide a representative dataset so the converter can calibrate
def representative_dataset():
    for images, _ in train_ds.take(100):
        yield [tf.cast(images, tf.float32)]

converter.representative_dataset = representative_dataset
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.int8

tflite_model_quant = converter.convert()
with open("model_quant.tflite", "wb") as f:
    f.write(tflite_model_quant)
```

**ONNX graph optimization with onnxruntime:**

```bash
python -m onnxruntime.tools.optimizer_cli \
  --input model.onnx \
  --output model_opt.onnx
  # Use --model_type to enable model-specific fusions, e.g.:
  #   --model_type bert       for transformer/BERT models
  #   --model_type gpt2       for GPT-2 models
  # Omit --model_type for generic CNN / image-classification models.
```

---

## Next Steps

- [Package the model in a Docker container and deploy with Kubernetes →](kubernetes.md)
- [Provision a Digital Ocean Kubernetes cluster →](digital-ocean.md)
- [End-to-end edge deployment workflow →](edge-deployment.md)
