import io
from datetime import datetime, timezone
from botocore.exceptions import ClientError


class FakeS3:
    """Tiny in-memory S3 so tests run without AWS."""
    def __init__(self, files=None):
        self.files = dict(files or {})

    def _missing(self, code, op):
        return ClientError({"Error": {"Code": code, "Message": "missing"}}, op)

    def head_object(self, Bucket, Key):
        if Key not in self.files:
            raise self._missing("404", "HeadObject")
        return {"ContentLength": len(self.files[Key])}

    def get_object(self, Bucket, Key):
        if Key not in self.files:
            raise self._missing("NoSuchKey", "GetObject")
        return {"Body": io.BytesIO(self.files[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.files[Key] = Body

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=100):
        now = datetime.now(timezone.utc)
        return {"Contents": [{"Key": k, "LastModified": now} for k in self.files if k.startswith(Prefix)]}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://signed.example/{Params['Key']}?exp={ExpiresIn}"
