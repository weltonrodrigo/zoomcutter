#!/usr/bin/env python3
"""
Zoom Video Processor - Automatically switches between speaker and side-by-side views
based on screen sharing chapters in Zoom recordings.
"""
import json
import subprocess
import sys
from pathlib import Path
import click


def get_video_info(video_file):
    """Extract video information (resolution, chapters) using ffprobe."""
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_streams',
        '-show_chapters',
        str(video_file)
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        # Extract video stream info
        video_stream = None
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                video_stream = stream
                break

        return {
            'chapters': data.get('chapters', []),
            'width': video_stream.get('width') if video_stream else None,
            'height': video_stream.get('height') if video_stream else None,
        }
    except subprocess.CalledProcessError as e:
        click.echo(f"Error running ffprobe: {e}", err=True)
        sys.exit(1)
    except json.JSONDecodeError as e:
        click.echo(f"Error parsing ffprobe output: {e}", err=True)
        sys.exit(1)


def get_sharing_intervals(chapters):
    """Extract sharing start/stop intervals from chapters."""
    intervals = []
    sharing_start = None

    for chapter in chapters:
        title = chapter.get('tags', {}).get('title', '')
        start_time = float(chapter['start_time'])

        if 'Sharing Started' in title:
            sharing_start = start_time
        elif 'Sharing Stopped' in title and sharing_start is not None:
            intervals.append((sharing_start, start_time))
            sharing_start = None

    # If sharing never stopped, extend to end
    if sharing_start is not None:
        # We'll handle this by using the video duration
        intervals.append((sharing_start, None))

    return intervals


def time_to_seconds(time_str):
    """Convert HH:MM:SS to seconds."""
    if not time_str:
        return None
    parts = time_str.split(':')
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    else:
        return float(parts[0])


def parse_dimensions(dim_str):
    """Parse dimension string like '1920x1080' or '1080p' into (width, height).

    Supported formats:
    - WIDTHxHEIGHT: e.g., '1920x1080', '1280x720'
    - HEIGHTp: e.g., '1080p' (assumes 16:9 ratio), '720p', '480p'

    Returns:
        tuple: (width, height) or None if invalid
    """
    if not dim_str:
        return None

    dim_str = dim_str.strip().lower()

    # Handle WIDTHxHEIGHT format
    if 'x' in dim_str:
        try:
            parts = dim_str.split('x')
            if len(parts) == 2:
                width = int(parts[0])
                height = int(parts[1])
                if width > 0 and height > 0:
                    return (width, height)
        except ValueError:
            return None

    # Handle HEIGHTp format (assumes 16:9 ratio)
    elif dim_str.endswith('p'):
        try:
            height = int(dim_str[:-1])
            # Common resolutions with 16:9 ratio
            width = int(height * 16 / 9)
            if width > 0 and height > 0:
                return (width, height)
        except ValueError:
            return None

    return None


def build_filter_complex(sharing_intervals, cam_width, cam_height, start_trim=None, end_trim=None,
                         output_width=None, output_height=None, layout='side-by-side',
                         background_color='black', background_image=None):
    """Build the ffmpeg filter_complex for dynamic layout switching.

    By default, uses camera's native resolution to minimize scaling:
    - Speaker-only: Camera at native resolution (no scaling!)
    - Side-by-side: Camera at half width + slides at half width
    - Diagonal: Slides large on left, camera small in bottom-right corner

    If output_width/output_height are specified, scales to those dimensions instead.

    Args:
        sharing_intervals: List of (start, end) tuples for screen sharing
        cam_width: Camera video width
        cam_height: Camera video height
        start_trim: Start trim time in seconds
        end_trim: End trim time in seconds
        output_width: Custom output width (optional)
        output_height: Custom output height (optional)
        layout: Layout type ('side-by-side' or 'diagonal')
        background_color: Background color (e.g., 'black', '#FF0000')
        background_image: Path to background image (optional)
    """

    # If we have trim times, adjust sharing intervals
    if start_trim or end_trim:
        adjusted_intervals = []
        for start, end in sharing_intervals:
            # Adjust relative to trim start
            if start_trim:
                start = max(0, start - start_trim)
                if end:
                    end = end - start_trim

            # Skip intervals outside trim range
            if end_trim and start >= (end_trim - (start_trim or 0)):
                continue
            if end and end <= 0:
                continue

            # Adjust end if it exceeds trim end
            if end_trim and (end is None or end > (end_trim - (start_trim or 0))):
                end = end_trim - (start_trim or 0)

            adjusted_intervals.append((start, end))
        sharing_intervals = adjusted_intervals

    # Build the enable expressions for each mode
    # Mode 1: Speaker only (when NOT sharing)
    # Mode 2: Side-by-side (when sharing)

    speaker_enable = []
    sidebyside_enable = []

    # Start with speaker mode from beginning
    if not sharing_intervals or sharing_intervals[0][0] > 0:
        speaker_enable.append(f"lt(t,{sharing_intervals[0][0] if sharing_intervals else 'inf'})")

    for i, (share_start, share_end) in enumerate(sharing_intervals):
        # During sharing: side-by-side
        if share_end is None:
            sidebyside_enable.append(f"gte(t,{share_start})")
        else:
            sidebyside_enable.append(f"between(t,{share_start},{share_end})")

            # After sharing stops: speaker only (until next sharing or end)
            if i + 1 < len(sharing_intervals):
                next_start = sharing_intervals[i + 1][0]
                speaker_enable.append(f"between(t,{share_end},{next_start})")
            else:
                speaker_enable.append(f"gte(t,{share_end})")

    # Build enable filter expressions
    speaker_expr = '+'.join(speaker_enable) if speaker_enable else '0'
    sidebyside_expr = '+'.join(sidebyside_enable) if sidebyside_enable else '0'

    # Calculate dimensions
    # Use custom output dimensions if provided, otherwise use camera native resolution
    final_width = output_width if output_width else cam_width
    final_height = output_height if output_height else cam_height

    # Determine if we need to scale camera feed
    needs_camera_scaling = (output_width is not None and output_height is not None)

    # Build the complete filter
    filter_parts = []

    # Create background canvas if using background image or custom color
    if background_image:
        # Load background image and scale to output size
        filter_parts.append(
            f"movie={background_image}:loop=0,setpts=N/(FRAME_RATE*TB),"
            f"scale={final_width}:{final_height}:force_original_aspect_ratio=decrease,"
            f"pad={final_width}:{final_height}:(ow-iw)/2:(oh-ih)/2:{background_color}[bg]"
        )
        base_canvas = "[bg]"
    elif background_color != 'black':
        # Create colored canvas
        filter_parts.append(
            f"color=c={background_color}:s={final_width}x{final_height}[bg]"
        )
        base_canvas = "[bg]"
    else:
        base_canvas = None

    # Process camera feed (input 0)
    filter_parts.append(
        "[0:v]split=2[cam_full][cam_half]"
    )

    # Full screen camera (speaker only mode)
    if needs_camera_scaling:
        # Scale camera to match output dimensions
        if base_canvas:
            filter_parts.append(
                f"[cam_full]scale={final_width}:-1:force_original_aspect_ratio=decrease,"
                f"pad={final_width}:{final_height}:(ow-iw)/2:(oh-ih)/2:{background_color}[cam_speaker_sized];"
                f"{base_canvas}[cam_speaker_sized]overlay=(W-w)/2:(H-h)/2[cam_speaker]"
            )
        else:
            filter_parts.append(
                f"[cam_full]scale={final_width}:-1:force_original_aspect_ratio=decrease,"
                f"pad={final_width}:{final_height}:(ow-iw)/2:(oh-ih)/2:black[cam_speaker]"
            )
    else:
        # No scaling needed
        if base_canvas:
            filter_parts.append(
                f"[cam_full]scale={final_width}:-1:force_original_aspect_ratio=decrease,"
                f"pad={final_width}:{final_height}:(ow-iw)/2:(oh-ih)/2:{background_color}[cam_speaker_sized];"
                f"{base_canvas}[cam_speaker_sized]overlay=(W-w)/2:(H-h)/2[cam_speaker]"
            )
        else:
            filter_parts.append(
                "[cam_full]copy[cam_speaker]"
            )

    # Build layout based on selected mode
    if layout == 'diagonal':
        # Diagonal layout: Large slides on left, small camera in bottom-right
        # Slides take ~72% width, camera ~30% width in corner
        slides_width = int(final_width * 0.72)
        cam_small_width = int(final_width * 0.30)

        # Calculate positions: camera in bottom-right with small margin
        margin = 20
        cam_x = final_width - cam_small_width - margin
        cam_y = final_height - int(cam_small_width * 0.75) - margin  # Assuming 4:3 aspect ratio for camera

        # Scale camera to small size
        filter_parts.append(
            f"[cam_half]scale={cam_small_width}:-1:force_original_aspect_ratio=decrease[cam_small]"
        )

        # Scale slides to large size on left
        filter_parts.append(
            f"[1:v]scale={slides_width}:-1:force_original_aspect_ratio=decrease,"
            f"pad={final_width}:{final_height}:0:(oh-ih)/2:{background_color}[slides_pad]"
        )

        # Overlay camera on bottom-right of slides
        filter_parts.append(
            f"[slides_pad][cam_small]overlay={cam_x}:{cam_y}[combined]"
        )

    else:  # side-by-side (default)
        # Side-by-side: Camera at half width + slides at half width
        half_width = final_width // 2

        # Half screen camera
        filter_parts.append(
            f"[cam_half]scale={half_width}:-1:force_original_aspect_ratio=decrease,"
            f"pad={half_width}:{final_height}:(ow-iw)/2:(oh-ih)/2:{background_color}[cam_side]"
        )

        # Process slides - scale to half width
        filter_parts.append(
            f"[1:v]scale={half_width}:-1:force_original_aspect_ratio=decrease,"
            f"pad={half_width}:{final_height}:(ow-iw)/2:(oh-ih)/2:{background_color}[slides]"
        )

        # Create side-by-side layout
        filter_parts.append(
            "[slides][cam_side]hstack=inputs=2[combined]"
        )

    # Select between speaker-only and combined layout based on time
    filter_parts.append(
        f"[cam_speaker][combined]"
        f"overlay=enable='{sidebyside_expr}':x=0:y=0[v]"
    )

    return ';'.join(filter_parts)


@click.command()
@click.argument('camera_file', type=click.Path(exists=True))
@click.argument('slides_file', type=click.Path(exists=True))
@click.argument('output_file', type=click.Path())
@click.option('--start', '-ss', help='Start time (HH:MM:SS)')
@click.option('--end', '-to', help='End time (HH:MM:SS)')
@click.option('--dimensions', '-d', help='Output dimensions (e.g., "1920x1080" or "1080p"). Default: camera native resolution')
@click.option('--layout', '-l',
              type=click.Choice(['side-by-side', 'diagonal'], case_sensitive=False),
              default='side-by-side',
              help='Layout mode: side-by-side (50/50 split) or diagonal (large slides with small camera overlay)')
@click.option('--background-color', '-bg',
              default='black',
              help='Background color (e.g., "black", "white", "#FF0000")')
@click.option('--background-image', '-bgi',
              type=click.Path(exists=True),
              help='Background image file (optional)')
@click.option('--dry-run', is_flag=True, help='Print ffmpeg command without executing')
def main(camera_file, slides_file, output_file, start, end, dimensions, layout, background_color, background_image, dry_run):
    """
    Process Zoom recordings to automatically switch between speaker and side-by-side views.

    CAMERA_FILE: Video file with camera feed (e.g., *_avo_*.mp4)
    SLIDES_FILE: Video file with screen sharing (e.g., *_as_*.mp4)
    OUTPUT_FILE: Output video file
    """
    click.echo(f"Processing Zoom recordings...")
    click.echo(f"  Camera: {camera_file}")
    click.echo(f"  Slides: {slides_file}")
    click.echo(f"  Output: {output_file}")

    # Get camera resolution
    cam_info = get_video_info(camera_file)
    cam_width = cam_info['width']
    cam_height = cam_info['height']

    if not cam_width or not cam_height:
        click.echo("Error: Could not detect camera resolution", err=True)
        sys.exit(1)

    click.echo(f"\nCamera resolution: {cam_width}x{cam_height}")

    # Parse chapters from slides file
    slides_info = get_video_info(slides_file)
    chapters = slides_info['chapters']
    click.echo(f"\nFound {len(chapters)} chapters")

    # Extract sharing intervals
    sharing_intervals = get_sharing_intervals(chapters)
    click.echo(f"Found {len(sharing_intervals)} screen sharing intervals:")
    for i, (start_t, end_t) in enumerate(sharing_intervals, 1):
        end_str = f"{end_t:.2f}s" if end_t else "end"
        click.echo(f"  {i}. {start_t:.2f}s - {end_str}")

    # Convert trim times
    start_seconds = time_to_seconds(start) if start else None
    end_seconds = time_to_seconds(end) if end else None

    if start_seconds:
        click.echo(f"\nTrimming from: {start} ({start_seconds}s)")
    if end_seconds:
        click.echo(f"Trimming to: {end} ({end_seconds}s)")

    # Parse custom dimensions if provided
    output_width = None
    output_height = None
    if dimensions:
        parsed_dims = parse_dimensions(dimensions)
        if parsed_dims:
            output_width, output_height = parsed_dims
            click.echo(f"\nOutput resolution: {output_width}x{output_height} (custom)")
            if output_width != cam_width or output_height != cam_height:
                click.echo(f"  - Camera will be scaled from {cam_width}x{cam_height}")
        else:
            click.echo(f"\nError: Invalid dimension format '{dimensions}'", err=True)
            click.echo("  Use formats like '1920x1080' or '1080p'", err=True)
            sys.exit(1)
    else:
        # Use camera native resolution for maximum speed
        # No upscaling = better performance, and streaming services will re-encode anyway
        click.echo(f"\nOutput resolution: {cam_width}x{cam_height} (camera native)")

    click.echo(f"Layout mode: {layout}")
    if layout == 'diagonal':
        click.echo(f"  - Speaker-only mode: Full camera view")
        click.echo(f"  - Sharing mode: Large slides (~72% width) with small camera overlay (bottom-right)")
    else:
        click.echo(f"  - Speaker-only mode: No scaling (maximum performance!)")
        click.echo(f"  - Side-by-side mode: 50/50 split")

    if background_image:
        click.echo(f"Background: Image from {background_image}")
    elif background_color != 'black':
        click.echo(f"Background color: {background_color}")

    # Build filter (don't pass trim times to filter since we're using -ss/-to)
    # The sharing intervals remain in absolute time, but ffmpeg will handle the offset
    filter_complex = build_filter_complex(
        sharing_intervals, cam_width, cam_height, start_seconds, end_seconds,
        output_width, output_height, layout=layout, background_color=background_color,
        background_image=background_image
    )

    # Build ffmpeg command with -ss BEFORE inputs for fast seeking
    cmd = ['ffmpeg']

    # Add -ss before each input for fast seeking (seeks before decoding)
    if start:
        cmd.extend(['-ss', start])
    cmd.extend(['-i', camera_file])

    if start:
        cmd.extend(['-ss', start])
    cmd.extend(['-i', slides_file])

    # Add -to for output duration (if provided)
    if end:
        # Calculate duration from start
        if start_seconds:
            duration = end_seconds - start_seconds
            cmd.extend(['-t', str(duration)])
        else:
            cmd.extend(['-to', end])

    cmd.extend([
        '-filter_complex', filter_complex,
        '-map', '[v]',
        '-map', '0:a',
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-crf', '18',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        output_file
    ])

    if dry_run:
        click.echo("\n" + "=" * 80)
        click.echo("FFMPEG COMMAND:")
        click.echo("=" * 80)
        click.echo(' '.join(cmd))
        return

    click.echo("\nRunning ffmpeg...")
    try:
        subprocess.run(cmd, check=True)
        click.echo(f"\n✓ Successfully created: {output_file}")
    except subprocess.CalledProcessError as e:
        click.echo(f"\n✗ Error running ffmpeg: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
