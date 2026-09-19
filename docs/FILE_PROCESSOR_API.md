# File Processor API

AIPromptBridge exposes a synchronous File Processor API while the app is
running. It binds to loopback only: use `AIPB_URL` to select the configured
local address (normally `http://127.0.0.1:5000`). It has no API token because
it can read local files and use the profiles already configured in the app;
never expose it through a reverse proxy or LAN interface.

```sh
export AIPB_URL=http://127.0.0.1:5000
```

## Endpoints

| Method   | Path                                   | Result                                                                                                                 |
| -------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `GET`    | `/file-processor/capabilities`         | Prompt names, enabled profile names, supported file/audio options, and `busy`. No profile or key secrets are returned. |
| `POST`   | `/file-processor/jobs`                 | Validate and run a synchronous job.                                                                                    |
| `GET`    | `/file-processor/jobs/<job_id>`        | Read a retained failed job.                                                                                            |
| `POST`   | `/file-processor/jobs/<job_id>/resume` | Retry remaining work with option overrides.                                                                            |
| `DELETE` | `/file-processor/jobs/<job_id>`        | Remove a retained job and its temporary data.                                                                          |

A malformed request returns `400`; a valid request that cannot run (missing
file, unavailable dependency, collision, or invalid profile) returns `422`.
A simultaneous job returns `409`. Successful jobs return `200` and their job
artifacts are deleted. Failed jobs return `422`, preserving outputs already
written, errors, metadata, and checkpoint for resume. Delete returns `204`.

## Job request

Every job requires `input_path`, exactly one of `prompt_name` or literal
`prompt`, an enabled saved `profile_name`, and `output`:

```json
{
  "input_path": "/recordings/interview.m4a",
  "recursive": false,
  "file_types": ["audio"],
  "prompt_name": "Transcribe (Native Verbatim)",
  "profile_name": "Transcription",
  "output": {
    "mode": "individual",
    "path": "/recordings/output",
    "naming": "{filename}_transcript",
    "extension": ".md",
    "overwrite": false
  },
  "delay": 1.0,
  "use_batch": false,
  "include_filename": true,
  "custom_instructions": "Speakers are Alice and Bob.",
  "per_file_instructions": { "/recordings/other.m4a": "This file is Spanish." },
  "large_file_mode": "files_api"
}
```

Paths expand `~` and environment variables and are resolved to absolute paths.
A file is processed directly; a directory is scanned in deterministic path
order, optionally recursively, then filtered by `file_types` (`image`,
`audio`, `text`, `document`, `code`). `individual` names one output per input;
`combined` requires multiple inputs. Naming supports `{filename}`,
`{extension}`, `{date}`, `{time}`, and `{index}`. Templates cannot contain path
separators. Existing or duplicate planned outputs fail before provider work
unless `output.overwrite` is true for existing outputs.

`use_batch` and `files_api` require a Google profile. `large_file_mode` is one
of `files_api`, `chunking`, or `skip`; chunking requires FFmpeg and applies to
audio. Profiles are names only: configure provider, model, base URL, and keys
in AIPromptBridge first. Requests never contain API keys or upstream URLs.

Optional `pdf` is `{ "split": false, "page_range": "all" }`; splitting
requires pypdf and accepts ranges such as `1-3,5`. Optional `transcription`
contains `model`, `mode` (`VERBATIM` or `SMART`), `diarization`,
`word_timestamp`, `language_codes`, and `custom_vocabulary`. SMART cannot use
diarization or word timestamps. Native transcription always uses the existing
Gemini Files API flow.

Optional `audio` is null, `{ "type": "normalize" }`, `amplify` or
`amplify_normalize` with positive `volume_percent`, a `preset` with
`preset_id`/`intensity`/optional `arnndn_model`, or `custom` with up to 32
supported effects. It may include `optimization` (`convert_to_mono`, supported
`sample_rate`, `bitrate_kbps`) and `force_no_chunking`. Audio processing
requires FFmpeg.

## Response and resume

```json
{
  "success": true,
  "job_id": "a1b2c3d4",
  "status": "completed",
  "processed_count": 1,
  "failed_count": 0,
  "total_count": 1,
  "output_path": null,
  "output_paths": ["/recordings/output/interview_transcript.md"],
  "output_paths_relative": ["/recordings/output/interview_transcript.md"],
  "errors": [],
  "elapsed_time": 12.4
}
```

`output_path` is set for combined output and is also included in `output_paths`.
Partial failures retain a job ID and return `success: false`. Resume accepts a
patch of processing options (prompt, profile, output, delay, batch, PDF,
transcription, audio, and overwrite) but rejects immutable scan fields:
`input_path`, `recursive`, and `file_types`. It processes only remaining files.

## Examples

Use a JSON file for large or multiline prompts. `jq` extracts the chained path;
Python can parse the JSON instead when jq is unavailable.

```sh
curl --fail --silent --show-error --max-time 0 -H 'Content-Type: application/json' \
  --data @transcribe.json "$AIPB_URL/file-processor/jobs" > transcribe-result.json
transcript=$(jq -r '.output_paths[0]' transcribe-result.json)
jq -n --arg input "$transcript" '{input_path:$input,prompt_name:"Digest Content",profile_name:"Default",output:{mode:"individual",path:"/recordings/output",naming:"{filename}_digest",extension:".md",overwrite:false}}' > digest.json
curl --fail --silent --show-error --max-time 0 -H 'Content-Type: application/json' --data @digest.json "$AIPB_URL/file-processor/jobs"
```

```powershell
$body = @{ input_path='C:\recordings\interview.m4a'; prompt_name='Digest Content'; profile_name='Default'; output=@{mode='individual';path='C:\recordings\output';naming='{filename}_digest';extension='.md';overwrite=$false} } | ConvertTo-Json -Depth 8
$response = Invoke-RestMethod "$env:AIPB_URL/file-processor/jobs" -Method Post -ContentType 'application/json' -Body $body
$response.output_paths[0]
```

```python
import os, requests

url = os.environ.get("AIPB_URL", "http://127.0.0.1:5000")
payload = {
    "input_path": "/tmp/input.txt",
    "prompt": "Summarize this.",
    "profile_name": "Default",
    "output": {"mode": "individual", "path": "/tmp/output", "naming": "{filename}_summary", "extension": ".md"},
}
response = requests.post(f"{url}/file-processor/jobs", json=payload, timeout=None)
response.raise_for_status()
print(response.json()["output_paths"][0])
```
