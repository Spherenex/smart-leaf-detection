import tensorflow as tf
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.layers import Dense, GlobalAveragePooling2D, Dropout
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import Adam
import os

# ✅ Paths
train_dir = r"C:\Users\Pradeep Gowda\Dropbox\My PC (LAPTOP-DOP3631L)\Desktop\manojSpherenex\Plant Disease\Train"
val_dir = r"C:\Users\Pradeep Gowda\Dropbox\My PC (LAPTOP-DOP3631L)\Desktop\manojSpherenex\Plant Disease\Validation"
test_dir = r"C:\Users\Pradeep Gowda\Dropbox\My PC (LAPTOP-DOP3631L)\Desktop\manojSpherenex\Plant Disease\Test"

# ✅ Parameters
IMG_SIZE = (224, 224)
BATCH_SIZE = 32
EPOCHS = 30  # Increase for better accuracy

# ✅ Data Augmentation
train_gen = ImageDataGenerator(
    rescale=1./255,
    rotation_range=25,
    width_shift_range=0.1,
    height_shift_range=0.1,
    shear_range=0.2,
    zoom_range=0.2,
    horizontal_flip=True,
    fill_mode='nearest'
)

val_gen = ImageDataGenerator(rescale=1./255)
test_gen = ImageDataGenerator(rescale=1./255)

# ✅ Generators
train_data = train_gen.flow_from_directory(
    train_dir,
    target_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    class_mode='categorical'
)

print("✅ Class indices used for training:")
print(train_data.class_indices)

val_data = val_gen.flow_from_directory(
    val_dir,
    target_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    class_mode='categorical'
)

test_data = test_gen.flow_from_directory(
    test_dir,
    target_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    class_mode='categorical',
    shuffle=False
)

# ✅ Load MobileNetV2 base
base_model = MobileNetV2(weights='imagenet', include_top=False, input_shape=(224, 224, 3))
base_model.trainable = False  # freeze base

# ✅ Add custom head
x = base_model.output
x = GlobalAveragePooling2D()(x)
x = Dropout(0.3)(x)
x = Dense(128, activation='relu')(x)
x = Dropout(0.3)(x)
predictions = Dense(train_data.num_classes, activation='softmax')(x)

model = Model(inputs=base_model.input, outputs=predictions)

# ✅ Compile
model.compile(optimizer=Adam(learning_rate=0.0001),
              loss='categorical_crossentropy',
              metrics=['accuracy'])

# ✅ Train (initial frozen base)
print("\n🔄 Starting initial training (frozen base model)...")
history_1 = model.fit(
    train_data,
    validation_data=val_data,
    epochs=EPOCHS
)

# ✅ Fine-tune (unfreeze some layers)
print("\n🔄 Fine-tuning MobileNetV2 layers...")
base_model.trainable = True
for layer in base_model.layers[:100]:  # freeze first 100 layers
    layer.trainable = False

# Recompile with lower learning rate
model.compile(optimizer=Adam(learning_rate=1e-5),
              loss='categorical_crossentropy',
              metrics=['accuracy'])

history_2 = model.fit(
    train_data,
    validation_data=val_data,
    epochs=30  # fine-tuning epochs
)

# ✅ Evaluate
loss, acc = model.evaluate(test_data)
print(f"✅ Test Accuracy: {acc*100:.2f}%")

# ✅ Save model
model.save("model_new2.h5")
print("✅ Model saved as model_new1.h5")
