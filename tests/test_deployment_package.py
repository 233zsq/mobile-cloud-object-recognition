"""Deployment guards: tampered files and approvals for another model must fail."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_package', ROOT/'deploy/runtime/verify_package.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class DeploymentPackageTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root/'release').mkdir()
        (self.root/'release/model.tflite').write_bytes(b'fixture: no inference is performed')
        labels = [f'class_{i}' for i in range(10)]
        (self.root/'release/labels.txt').write_text('\n'.join(labels)+'\n', encoding='utf-8')
        self.metadata = {'status':'frozen','model_version':'test-v2',
                         'sha256':verifier.sha256(self.root/'release/model.tflite'),
                         'labels_sha256':verifier.sha256(self.root/'release/labels.txt'),
                         'model_bytes':(self.root/'release/model.tflite').stat().st_size,
                         'categories':[{'label_key':label} for label in labels],
                         'deployment_approval':'pending_human_approval'}
        self.write('release/metadata.json',self.metadata)
        self.write('comparison.json',{'candidate':{'sha256':self.metadata['sha256']}})
        self.approval = {'status':'approved','model_version':'test-v2','model_sha256':self.metadata['sha256'],
                         'report_sha256':verifier.sha256(self.root/'comparison.json')}
        self.write('release/approval.json',self.approval)
        self.inventory()

    def write(self,name,value):
        (self.root/name).write_text(json.dumps(value)+'\n', encoding='utf-8')

    def inventory(self):
        self.write('checksums.json',{'model_version':'test-v2',
                   'files':{str(p.relative_to(self.root)).replace('\\','/'):verifier.sha256(p)
                            for p in self.root.rglob('*') if p.is_file() and p.name!='checksums.json'}})

    def test_matching_approval_passes(self):
        self.assertTrue(verifier.verify_package(self.root)['passed'])

    def test_modified_model_is_rejected(self):
        (self.root/'release/model.tflite').write_bytes(b'changed')
        self.inventory()  # Even an updated inventory cannot override metadata identity.
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            verifier.verify_package(self.root)

    def test_other_model_approval_is_rejected(self):
        self.write('release/approval.json',dict(self.approval,model_sha256='0'*64))
        self.inventory()
        with self.assertRaisesRegex(ValueError,'Matching human approval'):
            verifier.verify_package(self.root)

    def test_unapproved_status_is_rejected(self):
        self.write('release/approval.json',dict(self.approval,status='rejected'))
        self.inventory()
        with self.assertRaisesRegex(ValueError,'Matching human approval'):
            verifier.verify_package(self.root)

    def test_different_comparison_is_rejected(self):
        self.write('comparison.json',{'candidate':{'sha256':'0'*64}})
        self.write('release/approval.json',dict(self.approval,report_sha256=verifier.sha256(self.root/'comparison.json')))
        self.inventory()
        with self.assertRaisesRegex(ValueError,'Matching human approval'):
            verifier.verify_package(self.root)

    def test_traversal_in_inventory_is_rejected(self):
        self.write('checksums.json',{'model_version':'test-v2','files':{'../outside.txt':'0'*64}})
        with self.assertRaisesRegex(ValueError,'missing or hash mismatch'):
            verifier.verify_package(self.root)

    def test_wrong_label_order_is_rejected(self):
        self.metadata['categories'].reverse()
        self.write('release/metadata.json',self.metadata)
        self.inventory()
        with self.assertRaisesRegex(ValueError,'Category order'):
            verifier.verify_package(self.root)


if __name__ == '__main__':
    unittest.main()
