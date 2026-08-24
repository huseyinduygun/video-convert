import modal

app = modal.App("video-hls-processor")
volume = modal.Volume.from_name("hls-temp-storage-v2", create_if_missing=True, version=2)
