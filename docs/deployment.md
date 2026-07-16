# Alibaba Cloud deployment

## Status and target

The repository is packaged for **Alibaba Cloud ECS with Docker in Singapore (`ap-southeast-1`)**. No live deployment is claimed by this repository. The deployment evidence is the tested Docker artifact, health route, persistent data contract, and the Qwen Cloud provider path in `videoforge/providers/qwen_cloud.py`.

ECS is preferred for this MVP because video jobs run asynchronously for minutes and must keep a recoverable worker alive. Function Compute would require a separate queue/worker design to avoid request-lifetime coupling.

## Build

```bash
docker build -t videoforge-showrunner:0.1.0 .
```

Optional Alibaba Cloud Container Registry flow:

```bash
docker tag videoforge-showrunner:0.1.0 \
  registry.ap-southeast-1.aliyuncs.com/YOUR_NAMESPACE/videoforge:0.1.0
docker push registry.ap-southeast-1.aliyuncs.com/YOUR_NAMESPACE/videoforge:0.1.0
```

## Production environment

Create `/opt/videoforge/.env` on the ECS host:

```dotenv
SHOWRUNNER_PROVIDER=qwen
QWEN_API_KEY=server-side-singapore-key
QWEN_WORKSPACE_ID=workspace-id
QWEN_REGION=ap-southeast-1
QWEN_TEXT_MODEL=qwen-plus
QWEN_VISION_MODEL=qwen3-vl-plus
QWEN_IMAGE_MODEL=qwen-image-2.0
QWEN_VIDEO_MODEL=wan2.7-i2v
VIDEOFORGE_DATABASE=/app/data/videoforge.db
VIDEOFORGE_ASSET_ROOT=/app/data/assets
MAX_SHOTS=6
MAX_VIDEO_DURATION_SECONDS=5
MAX_PROJECT_RETRIES=3
MAX_CONCURRENT_VIDEO_TASKS=2
```

Use an ECS security group that exposes the application only through the intended reverse proxy/load balancer. Keep `.env` readable only by the service account.

## Start

```bash
docker run -d \
  --name videoforge \
  --restart unless-stopped \
  --env-file /opt/videoforge/.env \
  -v /opt/videoforge/data:/app/data \
  -p 8000:8000 \
  videoforge-showrunner:0.1.0
```

The image starts:

```text
uvicorn videoforge.app:app --host 0.0.0.0 --port 8000 --workers 1
```

One worker is intentional because the MVP job executor is in-process. SQLite and asset storage are persistent; job state is not memory-only.

## Health check

```bash
curl http://127.0.0.1:8000/api/health
```

The Docker `HEALTHCHECK` uses the same route. Configure the Alibaba load balancer health check to `GET /api/health` on port 8000.

## Storage behavior

Mount `/app/data` on an ECS data disk or NAS. It contains:

- `videoforge.db`: project, plan, job, provider, and report state
- `assets/`: downloaded images, videos, normalized clips, and final cuts

Generated provider URLs expire, so the worker downloads every result immediately. For multi-instance production, replace local assets with OSS and SQLite with managed RDS while preserving the provider/job interfaces.

## Restart behavior

At application startup, incomplete jobs are loaded from SQLite:

- queued work resumes;
- a Wan job with `remote_task_id` resumes polling rather than resubmitting;
- an interrupted real image call without a recoverable task ID fails safely and requires a user retry;
- successful individual assets remain available after another shot or assembly failure.

## Region alignment

The API key, workspace-specific Model Studio endpoint, and model availability must all be Singapore-region resources. VideoForge constructs the native media endpoint from `QWEN_WORKSPACE_ID`; the text/vision client uses the compatible-mode endpoint on the same workspace domain.

