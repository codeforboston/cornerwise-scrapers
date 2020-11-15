import boto3
from datetime import datetime, timedelta
from dateutil import parser as dt_parser
import pytz
import requests

import hashlib
import json
import os
import subprocess
import tempfile
from urllib.parse import unquote_plus, quote_plus

import somervillema
# from . import cambridgema

from extractors import extract, s3doc
from extractors.utils import pdfinfo, pdf_to_text

try:
    Session = boto3.Session(profile_name="cornerwise")
    S3 = Session.client("s3")
except _:
    S3 = boto3.client("s3")


BucketName = os.environ.get("DOCS_BUCKET", "cornerwise-docs-dev")

CaseLoaders = {
    "somervillema": somervillema,
    # "cambridgema": cambridgema.get_proposals_since
}

def extract_doc_attributes(bucket, key):
    doc = s3doc.S3Doc(bucket, key)
    return extract.get_properties(doc)

def extract_text(bucket, key):
    """Uses pdftotext to extract the text of a PDF and writes the resulting text
    file back to the bucket

    """
    local_dir = tempfile.mkdtemp()
    basename = os.path.basename(key)
    local_file = os.path.join(local_dir, basename)

    print(bucket, key, local_file)

    S3.download_file(bucket, key, local_file)

    response = S3.get_object(Bucket=bucket, Key=key)
    metadata = response.get("Metadata", {})
    try:
        TZ = pytz.timezone(metadata.get("timezone", "US/Eastern"))
        info_data = pdfinfo(local_file)
        if "CreationDate" in info_data:
            cdate = dt_parser.parse(info_data["CreationDate"])
            metadata["doc_created"] = TZ.localize(cdate).isoformat()
        if "ModDate" in info_data:
            mdate = dt_parser.parse(info_data["ModDate"])
            metadata["doc_modified"] = TZ.localize(mdate).isoformat()
    except Exception as err:
        print(err)

    text_file = os.path.join(local_dir, f"{basename}.txt")
    pdf_to_text(local_file, text_file)
    stripped_name = os.path.splitext(basename)[0]
    out_path = os.path.join(os.path.dirname(key), f"{stripped_name}.txt")
    S3.upload_file(text_file, bucket, out_path,
                   ExtraArgs={ "StorageClass": "STANDARD_IA",
                               "ACL": "public-read",
                               "Metadata": metadata
                   })

def download_docs(since):
    """Upload recent documents to the bucket
    """
    for region, module in CaseLoaders.items():
        region_name = module.REGION_NAME
        cases = module.get_proposals_since(since)
        for case in cases:
            addresses = case["all_addresses"]
            address = "".join(addresses[0:1])
            for doc in case["documents"]:
                url = doc['url']
                url_hash = hashlib.sha1(url.encode()).hexdigest()
                ext = os.path.splitext(url)[1]
                out_key = os.path.join(
                    region, quote_plus(case["case_number"]), f"{url_hash}{ext}")
                print(f"Downloading {url} -> {out_key}")

                req = requests.get(url, stream=True)
                S3.upload_fileobj(req.raw, BucketName, out_key,
                                  ExtraArgs={ "StorageClass": "STANDARD_IA",
                                              "ACL": "public-read",
                                              "Metadata": {
                                                  "origin": url,
                                                  "document_title": doc.get("title", ""),
                                                  "tags": json.dumps(doc.get("tags", [])),
                                                  "timezone": module.TIMEZONE.zone,
                                                  "case_number": case["case_number"],
                                                  "address": address,
                                                  "addresses": json.dumps(addresses),
                                                  "region": region_name,
                                                  "region_id": region,
                                                  "field": doc.get("field", "")
                                              }
                                  })

def doc_uploaded(event, context):
    s3 = event["Records"][0]["s3"]
    s3obj = s3["object"]
    bucket = s3["bucket"]
    key = unquote_plus(s3obj["key"])

    extract_text(bucket["name"], key)

def download(event, context):
    download_docs(datetime.now() - timedelta(days=7))
