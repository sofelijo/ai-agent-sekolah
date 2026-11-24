import io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from werkzeug.datastructures import FileStorage
import bullying_evidence as evidence

def photo(name='foto.png'):
    stream=io.BytesIO();Image.new('RGB',(8,8),'red').save(stream,format='PNG');stream.seek(0)
    return FileStorage(stream=stream,filename=name,content_type='image/png')

def file(data,name):return FileStorage(stream=io.BytesIO(data),filename=name)

class BullyingEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'BULLYING_EVIDENCE_DIR':self.folder.name});self.env.start()
 def tearDown(self):self.env.stop();self.folder.cleanup()
 def test_photo_private_permissions_and_original_hash(self):
  upload=photo();raw=upload.stream.getvalue();item=evidence.store_evidence([upload])[0]
  path=evidence.evidence_path(item);self.assertEqual(path.read_bytes(),raw);self.assertEqual(path.stat().st_mode&0o777,0o600)
  self.assertEqual(item['mime'],'image/png');self.assertEqual(len(item['sha256']),64)
 def test_empty_upload_is_optional(self):self.assertEqual(evidence.store_evidence([]),[])
 def test_executable_disguised_as_photo_denied(self):
  with self.assertRaises(evidence.EvidenceError):evidence.store_evidence([file(b'MZevil','foto.jpg')])
  self.assertEqual(list(Path(self.folder.name).iterdir()),[])
 def test_unsupported_extension_denied(self):
  with self.assertRaises(evidence.EvidenceError):evidence.store_evidence([file(b'<svg/>','test.svg')])
 def test_too_many_files(self):
  with self.assertRaises(evidence.EvidenceError):evidence.store_evidence([photo() for _ in range(4)])
 def test_per_file_and_combined_limits(self):
  with patch.object(evidence,'MAX_FILE_BYTES',10),self.assertRaises(evidence.EvidenceError):evidence.store_evidence([photo()])
  with patch.object(evidence,'MAX_TOTAL_BYTES',100),self.assertRaises(evidence.EvidenceError):evidence.store_evidence([photo(),photo()])
  self.assertEqual(list(Path(self.folder.name).iterdir()),[])
 def test_second_bad_file_removes_first(self):
  with self.assertRaises(evidence.EvidenceError):evidence.store_evidence([photo(),file(b'bad','bad.jpg')])
  self.assertEqual(list(Path(self.folder.name).iterdir()),[])
 def test_video_header_and_stream_validated(self):
  with self.assertRaises(evidence.EvidenceError):evidence.store_evidence([file(b'MZevil','test.mp4')])
  result=type('Result',(),{'stdout':json.dumps({'streams':[{'codec_type':'video'}],'format':{'duration':'1','format_name':'mov,mp4'}})})()
  with patch.object(evidence.subprocess,'run',return_value=result):
   item=evidence.store_evidence([file(b'\x00\x00\x00\x18ftypisom0000','test.mp4')])[0];self.assertEqual(item['mime'],'video/mp4')
 def test_video_over_three_minutes_denied(self):
  result=type('Result',(),{'stdout':json.dumps({'streams':[{'codec_type':'video'}],'format':{'duration':'181','format_name':'mov,mp4'}})})()
  with patch.object(evidence.subprocess,'run',return_value=result),self.assertRaises(evidence.EvidenceError):evidence.store_evidence([file(b'\x00\x00\x00\x18ftypisom0000','test.mp4')])
 def test_traversal_and_symlink_denied(self):
  self.assertIsNone(evidence.evidence_path({'id':'../../secret','extension':'png'}))
  path=Path(self.folder.name)/('a'*32+'.png');path.symlink_to('/etc/passwd')
  self.assertIsNone(evidence.evidence_path({'id':'a'*32,'extension':'png'}))
if __name__=='__main__':unittest.main()
