class Storage:
    def __init__(self, client, bucket):
        self.client = client
        self.bucket = bucket

    def upload_image(self, file, key):
        import uuid


        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=file.read(),
            ContentType="image/png"
        )

        return key
    def get_url(self, key, expires=3600):

        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key
            },
            ExpiresIn=expires
        )