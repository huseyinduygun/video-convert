import modal

app = modal.App("video-hls-processor")
volume = modal.Volume.from_name("hls-temp-storage", create_if_missing=True)
