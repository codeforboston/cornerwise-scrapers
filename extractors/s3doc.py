from collections import namedtuple
import json

from dateutil.parser import parse as dt_parse
import boto3

class S3Doc():
    def __init__(self, bucket, key):
        self.S3 = boto3.client("s3")
        self.bucket = bucket
        self.key = key
        self._response = None

    @property
    def response(self):
        if not self._response:
            self._response = self.S3.get_object(Bucket=self.bucket, Key=self.key)
        return self._response

    @property
    def line_iterator(self):
        return self.response["Body"].iter_lines()

    @property
    def metadata(self):
        return self.response["Metadata"]

    @property
    def published(self):
        created = self.metadata.get("doc_created")
        if created:
            return dt_parse(created)

    @property
    def title(self):
        return self.metadata["document_title"]

    @property
    def tag_set(self):
        return json.loads(self.metadata["tags"])

    @property
    def region_name(self):
        return self.metadata["region_name"]

    @property
    def field(self):
        return self.metadata["field"]
