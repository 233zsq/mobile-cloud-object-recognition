"""Recheck the selected head with seed 43 on frozen development features only."""
import argparse
import hashlib
import json
from pathlib import Path
import keras
import numpy as np
import tensorflow as tf
from recognition.open_set import calibrate

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--experiment',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
if args.output.exists():
    raise ValueError('Preserve existing recheck')
if not tf.config.list_physical_devices('GPU'):
    raise ValueError('GPU recheck required')
for device in tf.config.list_physical_devices('GPU'):
    tf.config.experimental.set_memory_growth(device,True)
keras.utils.set_random_seed(43)
selection_path=args.experiment/'selection.json'
selection_hash=hashlib.sha256(selection_path.read_bytes()).hexdigest()
selection=json.loads(selection_path.read_text(encoding='utf8'))
if selection['candidate']!='mlp64':
    raise ValueError('This recheck implements the selected MLP64 workflow')
cache=args.experiment/'development-features.npz'
d=np.load(cache)
known=d['known_train']; unknown=d['unknown_train']
inputs=keras.Input((known.shape[1],))
x=keras.layers.Normalization(mean=known.mean(0),variance=np.maximum(known.var(0),.0001))(inputs)
x=keras.layers.Dense(64,activation='relu',kernel_regularizer=keras.regularizers.L2(.0001))(x)
x=keras.layers.Dropout(.2,seed=43)(x)
outputs=keras.layers.Dense(1,activation='sigmoid',kernel_regularizer=keras.regularizers.L2(.0001))(x)
head=keras.Model(inputs,outputs)
head.compile(optimizer=keras.optimizers.Adam(.0003),loss='binary_crossentropy')
train=np.concatenate([known,unknown]); labels=np.r_[np.ones(len(known)),np.zeros(len(unknown))].astype(np.float32)
weights=np.where(labels==1,len(labels)/(2*len(known)),len(labels)/(2*len(unknown))).astype(np.float32)
validation=np.concatenate([d['known_validation'],d['unknown_calibration']])
val_labels=np.r_[np.ones(len(d['known_validation'])),np.zeros(len(d['unknown_calibration']))].astype(np.float32)
args.output.mkdir(parents=True)
history=head.fit(train,labels,sample_weight=weights,validation_data=(validation,val_labels),batch_size=32,epochs=20,
    callbacks=[keras.callbacks.EarlyStopping(monitor='val_loss',patience=3,restore_best_weights=True),
    keras.callbacks.ModelCheckpoint(args.output/'best.keras',monitor='val_loss',save_best_only=True)],verbose=2)
vk=np.asarray(head(d['known_validation'],training=False)).reshape(-1)
uk=np.asarray(head(d['unknown_calibration'],training=False)).reshape(-1)
result=calibrate(d['validation_scores'],d['validation_labels'],vk,d['calibration_scores'],uk)
assert hashlib.sha256(selection_path.read_bytes()).hexdigest()==selection_hash
report={'seed':43,'selected_architecture':'mlp64','classification_weights_frozen':True,
    'feature_cache_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),'main_selection_sha256':selection_hash,
    'unknown_holdout_read':False,'project_test_images_read':False,'calibration':result['selected'],
    'main_calibration':selection['calibration'],'history':history.history,
    'limitations':['Frozen backbone features reused; only scope head initialization and training repeated.',
        'This is a development stability check, not a second independent acceptance test.']}
(args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:report[k] for k in ['seed','calibration','main_calibration']},ensure_ascii=False),flush=True)
