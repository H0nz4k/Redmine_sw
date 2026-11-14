import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

path=Path(__file__).with_name('worker.py')
spec=importlib.util.spec_from_file_location('local_summary_worker',path)
worker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

class FakeLlama:
    def __init__(self, **kwargs): pass
    def tokenize(self, data): return list(data)
    def create_chat_completion(self, **kwargs):
        return {'choices':[{'message':{'content':'Stručný testovací výstup.'},'finish_reason':'stop'}]}

class SummaryWorkerTests(unittest.TestCase):
    def run_worker(self,payload):
        input_stream=io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode('utf-8')),encoding='utf-8')
        output=io.StringIO()
        with patch.object(sys,'stdin',input_stream),patch.object(sys,'stdout',output),patch.dict(sys.modules,{'llama_cpp':type('Module',(),{'Llama':FakeLlama})}):
            worker.main()
        return json.loads(output.getvalue())
    def test_valid_summary(self):
        result=self.run_worker({'cases':[{'subject':'Pokus','description':'Vymyšlený požadavek'}]})
        self.assertEqual(result['results'][0]['summary'],'Stručný testovací výstup.')
    def test_rejects_unexpected_fields(self):
        with self.assertRaises(worker.InputError): self.run_worker({'cases':[{'subject':'A','description':'B','url':'http://example.invalid'}]})
    def test_rejects_oversized_description(self):
        with self.assertRaises(worker.InputError): self.run_worker({'cases':[{'subject':'A','description':'x'*5001}]})

if __name__=='__main__': unittest.main()
