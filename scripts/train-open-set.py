"""Train an auxiliary scope head while keeping all v2 classification weights frozen."""
import argparse
import csv
from datetime import datetime
import os
from pathlib import Path
import time
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-root', type=Path, required=True)
parser.add_argument('--data-version', default='campus-evolve-data-v2')
parser.add_argument('--release', type=Path, required=True)
parser.add_argument('--checkpoint', type=Path, required=True)
parser.add_argument('--aux-data', type=Path, required=True)
parser.add_argument('--diagnostic-image', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--early-layer', choices=['block_15_project_BN', 'block_15_expand_relu'], default='block_15_project_BN')
args = parser.parse_args()
os.environ['RECOGNITION_ROOT'] = str(args.data_root.resolve())
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
import keras
import numpy as np
import tensorflow as tf
from recognition.common import TZ, digest, image_path, now, read_json, write_json
from recognition.data import load_split
from recognition.open_set import accepted, calibrate, summarize
from recognition.preprocessing import preprocess, SPEC

if args.output.exists():
    raise ValueError('Use a new version; completed selections/holdouts cannot be overwritten')
if datetime.now(TZ).hour >= 23:
    raise RuntimeError('Do not start long experiments after 23:00 Beijing time')
metadata = read_json(args.release / 'metadata.json')
auxiliary = read_json(args.aux_data / 'metadata.json')
if digest(args.checkpoint) != metadata['checkpoint_sha256'] or digest(args.aux_data / 'samples.csv') != auxiliary['manifest_sha256']:
    raise ValueError('Baseline or auxiliary manifest hash differs')
with (args.aux_data / 'samples.csv').open(newline='', encoding='utf8') as handle:
    auxiliary_rows = list(csv.DictReader(handle))
if any(row['scope_target'] != '0' for row in auxiliary_rows):
    raise ValueError('Auxiliary labels must be explicit out-of-scope samples')
classes = {split: {row['semantic_class'] for row in auxiliary_rows if row['split'] == split} for split in ['train', 'calibration', 'holdout']}
if any(classes[a] & classes[b] for a, b in [('train', 'calibration'), ('train', 'holdout'), ('calibration', 'holdout')]):
    raise ValueError('Unknown semantic classes cross development splits')
gpus = tf.config.list_physical_devices('GPU')
if not gpus:
    raise RuntimeError('This run requires the existing GPU environment')
for gpu in gpus:
    tf.config.experimental.set_memory_growth(gpu, True)
tf.config.experimental.enable_tensor_float_32_execution(False)
keras.utils.set_random_seed(42)
base = keras.models.load_model(args.checkpoint, compile=False)
base.trainable = False
backbone = next(layer for layer in base.layers if isinstance(layer, keras.Model))
trunk = keras.Model(backbone.inputs, [backbone.get_layer(args.early_layer).output, backbone.output], name='scope_shared_backbone')
inputs = keras.Input(shape=(224, 224, 3), dtype='float32', name='rgb_pixels')
mid, final = trunk(base.get_layer('input_normalization')(inputs), training=False)
pool = next(layer for layer in base.layers if isinstance(layer, keras.layers.GlobalAveragePooling2D))
deep = pool(final)
early = keras.layers.GlobalAveragePooling2D(name='scope_early_pool')(mid)
features = keras.layers.Concatenate(name='scope_embedding')([deep, early])
dropout = next(layer for layer in base.layers if isinstance(layer, keras.layers.Dropout))
scores = base.get_layer('class_scores')(dropout(deep, training=False))
extractor = keras.Model(inputs, [features, scores])
args.output.mkdir(parents=True)
shutil.copyfile(Path(__file__), args.output / 'source-script.py')
start_time = time.perf_counter()


def extract(rows, name, root=None):
    result_features, result_scores = [], []
    for start in range(0, len(rows), 32):
        subset = rows[start:start+32]
        paths = [image_path(row['image_path']) if root is None else (root / row['image_path']).resolve() for row in subset]
        if root is not None and any(not path.is_relative_to(root.resolve()) for path in paths):
            raise ValueError('Auxiliary sample path escapes its data root')
        for path, row in zip(paths, subset):
            if digest(path) != row['image_sha256']:
                raise ValueError('Image identity changed')
        f, s = extractor(np.stack([preprocess(path) for path in paths]), training=False)
        result_features.append(np.asarray(f, dtype=np.float32)); result_scores.append(np.asarray(s, dtype=np.float32))
        if (start//32) % 10 == 0:
            print(name, min(start+32, len(rows)), '/', len(rows), flush=True)
    return np.concatenate(result_features), np.concatenate(result_scores)


known_train, train_meta = load_split(args.data_version, 'train')
known_validation, validation_meta = load_split(args.data_version, 'validation')
unknown_train = [row for row in auxiliary_rows if row['split'] == 'train']
unknown_calibration = [row for row in auxiliary_rows if row['split'] == 'calibration']
train_features, train_scores = extract(known_train, 'known train')
validation_features, validation_scores = extract(known_validation, 'known validation')
outlier_features, outlier_scores = extract(unknown_train, 'unknown train', args.aux_data)
calibration_features, calibration_scores = extract(unknown_calibration, 'unknown calibration', args.aux_data)
labels = np.array([int(row['category_id']) for row in known_validation])
np.savez_compressed(args.output / 'development-features.npz', known_train=train_features,
                    known_validation=validation_features, unknown_train=outlier_features,
                    unknown_calibration=calibration_features, validation_scores=validation_scores,
                    calibration_scores=calibration_scores, validation_labels=labels)
means = train_features.mean(axis=0)
variances = np.maximum(train_features.var(axis=0), .0001)
x = np.concatenate([train_features, outlier_features])
y = np.r_[np.ones(len(train_features)), np.zeros(len(outlier_features))].astype(np.float32)
weights = np.where(y == 1, len(y)/(2*len(train_features)), len(y)/(2*len(outlier_features))).astype(np.float32)
vx = np.concatenate([validation_features, calibration_features])
vy = np.r_[np.ones(len(validation_features)), np.zeros(len(calibration_features))].astype(np.float32)
candidates = []
heads = {}
for kind in ['linear', 'mlp64']:
    keras.utils.set_random_seed(42)
    head_input = keras.Input(shape=(train_features.shape[1],), name='scope_features')
    h = keras.layers.Normalization(mean=means, variance=variances, name='scope_feature_normalization')(head_input)
    if kind == 'mlp64':
        h = keras.layers.Dense(64, activation='relu', kernel_regularizer=keras.regularizers.L2(.0001), name='scope_hidden')(h)
        h = keras.layers.Dropout(.2, seed=42, name='scope_dropout')(h)
    knownness = keras.layers.Dense(1, activation='sigmoid', kernel_regularizer=keras.regularizers.L2(.0001), name='knownness')(h)
    head = keras.Model(head_input, knownness, name='scope_' + kind)
    head.compile(optimizer=keras.optimizers.Adam(.0003), loss='binary_crossentropy')
    callbacks = [keras.callbacks.EarlyStopping(monitor='val_loss', patience=3, restore_best_weights=True),
                 keras.callbacks.ModelCheckpoint(args.output / (kind + '-best.keras'), monitor='val_loss', save_best_only=True),
                 keras.callbacks.ModelCheckpoint(args.output / (kind + '-latest.keras'))]
    history = head.fit(x, y, sample_weight=weights, validation_data=(vx, vy), batch_size=32, epochs=20,
                       shuffle=True, callbacks=callbacks, verbose=2)
    vk = np.asarray(head(validation_features, training=False)).reshape(-1)
    uk = np.asarray(head(calibration_features, training=False)).reshape(-1)
    calibration = calibrate(validation_scores, labels, vk, calibration_scores, uk)
    candidate = {'kind': kind, 'epochs': len(history.history['loss']), 'history': history.history,
                 'checkpoint_sha256': digest(args.output / (kind + '-best.keras')), 'calibration': calibration}
    candidates.append(candidate); heads[kind] = head
    write_json(args.output / (kind + '-result.json'), candidate)
winner = max(candidates, key=lambda c: (c['calibration']['selected']['unknown_rejection_rate'],
                                       c['calibration']['selected']['known_coverage'], -['linear', 'mlp64'].index(c['kind'])))
selected = winner['calibration']['selected']
head = heads[winner['kind']]
selection = {'created_at': now(), 'status': 'experimental', 'rule': 'learned_knownness_v1',
             'parent_model_version': metadata['model_version'], 'parent_model_sha256': metadata['sha256'],
             'parent_checkpoint_sha256': metadata['checkpoint_sha256'],
             'candidate': winner['kind'], 'confidence_threshold': .55, 'margin_threshold': .20,
             'knownness_threshold': selected['threshold'], 'calibration': selected,
             'known_data_version': args.data_version, 'known_validation_sha256': validation_meta['files']['validation']['sha256'],
             'auxiliary_data_version': auxiliary['data_version'], 'auxiliary_manifest_sha256': auxiliary['manifest_sha256'],
             'feature_layers': [pool.name, args.early_layer],
             'feature_dimension': int(train_features.shape[1]), 'head_sha256': winner['checkpoint_sha256'],
             'classification_weights_frozen': True, 'protected_project_test_images_read': False,
             'unknown_holdout_read_at_selection': False,
             'script_sha256': digest(Path(__file__)), 'tensorflow': tf.__version__, 'keras': keras.__version__}
write_json(args.output / 'selection.json', selection)
# Nothing below this point may modify the selected head or thresholds.
selection_hash = digest(args.output / 'selection.json')
unknown_holdout = [row for row in auxiliary_rows if row['split'] == 'holdout']
holdout_features, holdout_scores = extract(unknown_holdout, 'unknown held-out semantic classes', args.aux_data)
vk = np.asarray(head(validation_features, training=False)).reshape(-1)
hk = np.asarray(head(holdout_features, training=False)).reshape(-1)
holdout_metrics = summarize(validation_scores, labels, vk, holdout_scores, hk, selected['threshold'])
diagnostic_features, diagnostic_scores = extractor(preprocess(args.diagnostic_image)[None, ...], training=False)
diagnostic_knownness = np.asarray(head(diagnostic_features, training=False)).reshape(-1)
diagnostic_accepted = bool(accepted(np.asarray(diagnostic_scores), diagnostic_knownness, selected['threshold'])[0])
candidate_model = keras.Model(inputs, {'class_scores': scores, 'knownness': head(features, training=False)}, name='campus_open_set')
candidate_model.save(args.output / 'candidate.keras')
candidate_model.export(args.output / 'saved_model', input_signature=[tf.TensorSpec([1, 224, 224, 3], tf.float32)], verbose=False)
converter = tf.lite.TFLiteConverter.from_saved_model(str(args.output / 'saved_model'))
converter.optimizations = []
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
blob = converter.convert()
(args.output / 'model.tflite').write_bytes(blob)
if len(blob) > 15_000_000:
    raise ValueError('Candidate exceeds the 15 MB model size target')
interpreter = tf.lite.Interpreter(model_content=blob, num_threads=1)
interpreter.allocate_tensors()
inputs_detail = interpreter.get_input_details()[0]
outputs_detail = interpreter.get_output_details()
score_output = next(detail for detail in outputs_detail if detail['shape'].tolist() == [1, 10])
scope_output = next(detail for detail in outputs_detail if detail['shape'].tolist() == [1, 1])
max_score_error = 0.; max_knownness_error = 0.; category_changes = 0
for start in range(0, len(known_validation), 32):
    rows = known_validation[start:start+32]
    images = np.stack([preprocess(image_path(row['image_path'])) for row in rows])
    expected_scores = validation_scores[start:start+len(rows)]
    expected_knownness = vk[start:start+len(rows)]
    for image, expected, expected_k in zip(images, expected_scores, expected_knownness):
        interpreter.set_tensor(inputs_detail['index'], image[None, ...]); interpreter.invoke()
        actual = interpreter.get_tensor(score_output['index'])[0]
        actual_k = float(interpreter.get_tensor(scope_output['index'])[0, 0])
        max_score_error = max(max_score_error, float(np.max(np.abs(actual-expected))))
        max_knownness_error = max(max_knownness_error, abs(actual_k-float(expected_k)))
        category_changes += int(actual.argmax() != expected.argmax())
    if start % 320 == 0: print('FP32 consistency', min(start+32, len(known_validation)), flush=True)
if max_score_error > .001 or max_knownness_error > .001 or category_changes:
    raise ValueError('FP32 exported candidate differs from the selected Keras model')
if digest(args.output / 'selection.json') != selection_hash:
    raise ValueError('Selection changed after holdout evaluation')
metrics = {'created_at': now(), 'status': 'experimental', 'selection_sha256': selection_hash,
           'selected_candidate': winner['kind'], 'validation_and_unknown_holdout': holdout_metrics,
           'development_gecko': {'knownness': float(diagnostic_knownness[0]), 'accepted': diagnostic_accepted,
                                 'scores': np.asarray(diagnostic_scores)[0].tolist(),
                                 'image_sha256': digest(args.diagnostic_image), 'used_for_training_or_selection': False},
           'artifact': {'model_sha256': digest(args.output / 'model.tflite'), 'model_bytes': len(blob),
                        'input': SPEC, 'score_output_tensor_index': int(score_output['index']),
                        'knownness_output_tensor_index': int(scope_output['index']),
                        'score_output_position': next(i for i, item in enumerate(outputs_detail) if item['index'] == score_output['index']),
                        'knownness_output_position': next(i for i, item in enumerate(outputs_detail) if item['index'] == scope_output['index'])},
           'consistency': {'known_validation_count': len(known_validation), 'max_score_error': max_score_error,
                           'max_knownness_error': max_knownness_error, 'category_changes': category_changes},
           'development_targets_met': holdout_metrics['known_coverage'] >= .90 and holdout_metrics['unknown_rejection_rate'] >= .80 and not diagnostic_accepted,
           'seconds': time.perf_counter()-start_time,
           'limitations': ['Known validation participates in calibration; it is not independent field acceptance.',
                          'Unknown holdout contains previously unseen source classes from one public dataset.',
                          'Phone OOD accuracy, iPhone Safari behavior and physical performance remain separate.']}
write_json(args.output / 'report.json', metrics)
print({key: metrics[key] for key in ['selected_candidate', 'validation_and_unknown_holdout', 'development_gecko', 'artifact', 'consistency', 'development_targets_met']}, flush=True)
