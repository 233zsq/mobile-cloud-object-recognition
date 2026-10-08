import numpy as np
import pytest


@pytest.mark.integration
def test_fine_tune_ranges_and_batchnorm_are_frozen():
    import keras
    from recognition.training import build,scope
    model=build({"pretrained_weights":None,"dropout":.2,"seed":42,"fine_tune_scope":"frozen"})
    assert len(model.trainable_weights)==2
    backbone=scope(model,"last_2")
    trained=[layer.name for layer in backbone.layers if layer.trainable]
    assert "Conv_1" in trained and any(n.startswith("block_15_") for n in trained)
    assert all(n=="Conv_1" or n.startswith(("block_15_","block_16_")) for n in trained)
    assert not any(layer.trainable for layer in backbone.layers if isinstance(layer,keras.layers.BatchNormalization))
    bn=next(layer for layer in backbone.layers if isinstance(layer,keras.layers.BatchNormalization))
    before=[v.numpy().copy() for v in bn.weights]
    target=next(layer for layer in backbone.layers if layer.name=="Conv_1")
    kernel=target.kernel.numpy().copy()
    model.compile(optimizer=keras.optimizers.Adam(.0001),loss="sparse_categorical_crossentropy")
    model.train_on_batch(np.random.default_rng(42).uniform(0,255,(2,224,224,3)).astype(np.float32),np.array([0,1]))
    for a,b in zip(before,bn.weights):
        np.testing.assert_array_equal(a,b.numpy())
    assert np.any(kernel!=target.kernel.numpy())
    scope(model,"last_1")
    assert not any(layer.trainable for layer in backbone.layers if layer.name.startswith("block_15_"))
