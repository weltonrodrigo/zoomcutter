# ZoomCutter

Automatically process Zoom recordings to switch between speaker-only and side-by-side views based on screen sharing chapters.

## What it does

ZoomCutter intelligently combines your Zoom camera and screen sharing recordings into a single video that:
- Shows **speaker-only view** when you're not sharing your screen
- Switches to **side-by-side view** (slides + camera) when screen sharing is detected
- Maintains camera's native resolution for optimal performance
- Uses Zoom's built-in chapter markers to detect sharing automatically

Perfect for creating professional-looking recordings of presentations, lectures, or meetings!

## Features

- **Automatic switching**: Reads Zoom chapter markers to detect when screen sharing starts/stops
- **Smart resolution handling**: Uses camera's native resolution (no unnecessary upscaling)
- **Trim support**: Cut your video to specific start/end times
- **Fast processing**: Optimized ffmpeg settings for quick encoding
- **Dry-run mode**: Preview the ffmpeg command before processing

## Installation

```bash
pip install zoomcutter
```

### Requirements

ZoomCutter requires **ffmpeg** to be installed on your system:

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt install ffmpeg
```

**Windows:**
Download from [ffmpeg.org](https://ffmpeg.org/download.html) or use [Chocolatey](https://chocolatey.org/):
```bash
choco install ffmpeg
```

## Usage

### Basic Usage

```bash
zoomcutter camera_file.mp4 slides_file.mp4 output.mp4
```

Where:
- `camera_file.mp4` - Your Zoom camera recording (usually named `*_avo_*.mp4`)
- `slides_file.mp4` - Your Zoom screen sharing recording (usually named `*_as_*.mp4`)
- `output.mp4` - The output filename

### Trim Video

Cut your video to a specific time range:

```bash
# Start at 2 minutes, end at 45 minutes
zoomcutter camera.mp4 slides.mp4 output.mp4 --start 00:02:00 --end 00:45:00

# Using short options
zoomcutter camera.mp4 slides.mp4 output.mp4 -ss 00:02:00 -to 00:45:00
```

### Dry Run

Preview the ffmpeg command without processing:

```bash
zoomcutter camera.mp4 slides.mp4 output.mp4 --dry-run
```

## How It Works

1. **Reads chapter markers**: ZoomCutter analyzes the screen sharing video file to find "Sharing Started" and "Sharing Stopped" chapter markers that Zoom automatically adds
2. **Detects camera resolution**: Uses the camera feed's native resolution for optimal quality
3. **Builds filter**: Creates an ffmpeg filter that:
   - Shows camera at full resolution when not sharing
   - Switches to side-by-side (slides on left, camera on right) during sharing
4. **Processes video**: Runs ffmpeg with optimized settings for fast, high-quality output

## Output Quality

- **Video codec**: H.264 with CRF 18 (high quality)
- **Preset**: veryfast (good balance of speed and compression)
- **Audio**: Copied directly from camera feed (no re-encoding)
- **Resolution**: Matches camera's native resolution

## Example

```bash
# Process a 1-hour Zoom recording
$ zoomcutter zoom_0.mp4 zoom_share.mp4 final.mp4

Processing Zoom recordings...
  Camera: zoom_0.mp4
  Slides: zoom_share.mp4
  Output: final.mp4

Camera resolution: 1920x1080

Found 12 chapters
Found 3 screen sharing intervals:
  1. 120.50s - 850.30s
  2. 1200.00s - 2400.50s
  3. 2800.00s - end

Output resolution: 1920x1080 (camera native)
  - Speaker-only mode: No scaling (maximum performance!)
  - Side-by-side mode: Only scales slides down

Running ffmpeg...

 Successfully created: final.mp4
```

## Troubleshooting

**Error: "Could not detect camera resolution"**
- Make sure the camera file is a valid video file
- Try running `ffprobe camera_file.mp4` to verify

**Error: "Error running ffprobe"**
- Ensure ffmpeg (which includes ffprobe) is installed and in your PATH

**No chapters found**
- Verify you're using the screen sharing file (`*_as_*.mp4`) for chapter detection
- Some older Zoom versions may not include chapters

## Development

### Setup

```bash
git clone https://github.com/weltonrodrigo/zoomcutter.git
cd zoomcutter
uv pip install -e .
```

### Run locally

```bash
python main.py camera.mp4 slides.mp4 output.mp4
```

## License

MIT License - see LICENSE file for details

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
