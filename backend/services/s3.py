import os, boto3
from botocore.config import Config

S3_ENDPOINT_URL=os.getenv("S3_ENDPOINT_URL")
S3_REGION=os.getenv("S3_REGION","us-east-1")
S3_ACCESS_KEY=os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY=os.getenv("S3_SECRET_KEY")
S3_BUCKET=os.getenv("S3_BUCKET","clips")
S3_USE_SSL=os.getenv("S3_USE_SSL","false").lower()=="true"

def client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=Config(s3={"addressing_style":"path"}),
        use_ssl=S3_USE_SSL,
        verify=S3_USE_SSL,
    )

def upload_file(path: str, key: str) -> str:
    c = client()
    c.upload_file(path, S3_BUCKET, key)
    url = c.generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET, "Key": key}, ExpiresIn=3600)
    return url
