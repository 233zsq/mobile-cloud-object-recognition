"""Readonly GPU feature probe for a frozen ten-class baseline; never opens test images."""
import argparse
import os
from pathlib import Path
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-root', type=Path, required=True)
parser.add_argument('--data-version', default='campus-evolve-data-v2')
parser.add_argument('--release', type=Path, required=True)
parser.add_argument('--checkpoint', type=Path, required=True)
parser.add_argument('--diagnostic-image', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
os.environ['RECOGNITION_ROOT'] = str(args.data_root.resolve())
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')

import keras
import numpy as np
import tensorflow as tf
from recognition.common import digest, image_path, now, read_json, write_json
from recognition.data import load_split
from recognition.preprocessing import preprocess

if args.output.exists():
    raise ValueError('Use a fresh diagnostic output directory')
metadata = read_json(args.release / 'metadata.json')
if digest(args.checkpoint) != metadata['checkpoint_sha256']:
    raise ValueError('Baseline checkpoint differs from frozen release')
gpus = tf.config.list_physical_devices('GPU')
if not gpus:
    raise RuntimeError('Activate the existing WSL GPU environment before the probe')
for gpu in gpus:
    tf.config.experimental.set_memory_growth(gpu, True)
tf.config.experimental.enable_tensor_float_32_execution(False)
keras.utils.set_random_seed(42)
model = keras.models.load_model(args.checkpoint, compile=False)
pool = next(layer for layer in model.layers if isinstance(layer, keras.layers.GlobalAveragePooling2D))
extractor = keras.Model(model.inputs, [pool.output, model.output])
args.output.mkdir(parents=True)
identity = {'created_at': now(), 'model_version': metadata['model_version'], 'model_sha256': metadata['sha256'],
            'checkpoint_sha256': metadata['checkpoint_sha256'], 'data_version': args.data_version,
            'feature_layer': pool.name, 'feature_dimension': int(pool.output.shape[-1]),
            'tensorflow': tf.__version__, 'keras': keras.__version__, 'device': [str(gpu) for gpu in gpus],
            'final_test_images_read': False, 'diagnostic_is_independent_test': False}
arrays = {}
started = time.perf_counter()
for split in ['train', 'validation']:
    rows, dataset = load_split(args.data_version, split)
    features, scores = [], []
    for start in range(0, len(rows), 32):
        images = np.stack([preprocess(image_path(row['image_path'])) for row in rows[start:start+32]])
        f, s = extractor(images, training=False)
        features.append(np.asarray(f, dtype=np.float32)); scores.append(np.asarray(s, dtype=np.float32))
        if (start // 32) % 10 == 0:
            print(f'{split}: {min(start+32, len(rows))}/{len(rows)}', flush=True)
    arrays[split + '_features'] = np.concatenate(features)
    arrays[split + '_scores'] = np.concatenate(scores)
    arrays[split + '_labels'] = np.array([int(row['category_id']) for row in rows])
    identity[split] = {'count': len(rows), 'manifest_sha256': dataset['files'][split]['sha256'],
                       'sample_ids': [row['sample_id'] for row in rows],
                       'image_sha256': [row['image_sha256'] for row in rows]}
f, s = extractor(preprocess(args.diagnostic_image)[None, ...], training=False)
arrays['diagnostic_features'] = np.asarray(f, dtype=np.float32)
arrays['diagnostic_scores'] = np.asarray(s, dtype=np.float32)
identity['diagnostic_image_sha256'] = digest(args.diagnostic_image)
np.savez_compressed(args.output / 'features.npz', **arrays)
identity['features_sha256'] = digest(args.output / 'features.npz')
identity['seconds'] = time.perf_counter() - started
normalize = lambda values: values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-12)
reference = normalize(arrays['train_features'])
validation = normalize(arrays['validation_features'])
diagnostic = normalize(arrays['diagnostic_features'])
similarities = validation @ reference.T
diagnostic_similarities = diagnostic @ reference.T
summary = {}
for k in [1, 5, 20]:
    distances = np.maximum(0, 2 - 2 * np.partition(similarities, -k, axis=1)[:, -k])
    diagnostic_distance = float(np.maximum(0, 2 - 2 * np.partition(diagnostic_similarities, -k, axis=1)[0, -k]))
    summary[str(k)] = {'known_validation_distance_quantiles': {str(q): float(np.quantile(distances, q)) for q in [.5, .9, .95, .99]},
                       'diagnostic_distance': diagnostic_distance,
                       'diagnostic_above_known_p95': diagnostic_distance > float(np.quantile(distances, .95))}
identity['knn_diagnostic'] = summary
identity['diagnostic_scores'] = arrays['diagnostic_scores'][0].tolist()
write_json(args.output / 'identity.json', identity)
print({'elapsed_seconds': identity['seconds'], 'knn': summary}, flush=True)
