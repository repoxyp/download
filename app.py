from flask import Flask, request, render_template, send_file, jsonify
import yt_dlp
import os
import uuid
import re

app = Flask(__name__)

DOWNLOAD_FOLDER = "downloads"
COOKIES_FILE = "cookies/cookies.txt" if os.path.exists("cookies/cookies.txt") else None

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

def fix_shorts_url(url):
    if 'youtube.com/shorts/' in url:
        video_id = url.split('/')[-1].split('?')[0]
        return f'https://www.youtube.com/watch?v={video_id}'
    return url

def get_video_formats(url):
    """ভিডিওর available ফরম্যাট এবং রেজোলিউশনগুলো fetch করে"""
    try:
        url = fix_shorts_url(url)
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        
        # কুকি ফাইল থাকলে ব্যবহার করবে, না থাকলে ছাড়াই কাজ করবে
        if COOKIES_FILE and os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            
            # সর্বোচ্চ কোয়ালিটি অপশন
            formats.append({
                'format_id': 'best',
                'name': 'Best Quality (Auto)',
                'resolution': 'best',
                'type': 'video'
            })
            
            # MP3 অডিও অপশন
            formats.append({
                'format_id': 'mp3',
                'name': 'MP3 Audio (128kbps)',
                'resolution': 'audio',
                'type': 'audio'
            })
            
            # available ভিডিও ফরম্যাটগুলো
            for f in info.get('formats', []):
                # শুধুমাত্র ভিডিও+অডিও combined ফরম্যাট
                if (f.get('video_ext') != 'none' and 
                    f.get('audio_ext') != 'none' and 
                    f.get('height') is not None):
                    
                    format_name = f"{f['height']}p"
                    if f.get('fps'):
                        format_name += f" ({int(f['fps'])}fps)"
                    
                    # ফাইল সাইজ যোগ করা
                    filesize = f.get('filesize') or f.get('filesize_approx')
                    if filesize:
                        size_mb = filesize / (1024 * 1024)
                        format_name += f" ({size_mb:.1f}MB)"
                    
                    formats.append({
                        'format_id': f['format_id'],
                        'name': format_name,
                        'resolution': f'{f["height"]}p',
                        'type': 'video',
                        'height': f['height']
                    })
                
                # উচ্চ রেজোলিউশনের জন্য separate ভিডিও+অডিও ফরম্যাট
                elif (f.get('video_ext') != 'none' and 
                      f.get('audio_ext') == 'none' and 
                      f.get('height') is not None and 
                      f.get('height') >= 720):
                    
                    format_name = f"{f['height']}p (Video Only)"
                    if f.get('fps'):
                        format_name += f" ({int(f['fps'])}fps)"
                    
                    filesize = f.get('filesize') or f.get('filesize_approx')
                    if filesize:
                        size_mb = filesize / (1024 * 1024)
                        format_name += f" ({size_mb:.1f}MB)"
                    
                    formats.append({
                        'format_id': f['format_id'] + '+bestaudio',
                        'name': format_name,
                        'resolution': f'{f["height"]}p',
                        'type': 'video_merge',
                        'height': f['height']
                    })
            
            # রেজোলিউশন অনুযায়ী সাজানো এবং ডুপ্লিকেট রিমুভ
            unique_formats = []
            seen = set()
            
            for f in formats:
                if f['type'] in ['video', 'video_merge']:
                    identifier = f["resolution"]
                else:
                    identifier = f["type"]
                
                if identifier not in seen:
                    unique_formats.append(f)
                    seen.add(identifier)
            
            # রেজোলিউশন অনুযায়ী সাজানো (উচ্চ থেকে নিম্ন)
            video_formats = [f for f in unique_formats if f['type'] in ['video', 'video_merge']]
            video_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
            
            other_formats = [f for f in unique_formats if f['type'] not in ['video', 'video_merge']]
            
            return other_formats + video_formats
            
    except Exception as e:
        print(f"Error getting formats: {e}")
        # যদি error হয়, তাহলে至少 basic অপশনগুলো রিটার্ন করবে
        return [
            {'format_id': 'best', 'name': 'Best Quality (Auto)', 'resolution': 'best', 'type': 'video'},
            {'format_id': 'mp3', 'name': 'MP3 Audio', 'resolution': 'audio', 'type': 'audio'}
        ]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_formats', methods=['POST'])
def get_formats():
    """ভিডিওর available ফরম্যাটগুলো রিটার্ন করে"""
    url = request.json.get('url', '')
    if not url:
        return jsonify([])
    
    formats = get_video_formats(url)
    return jsonify(formats)

@app.route('/download', methods=['POST'])
def download():
    url = request.form['url']
    format_id = request.form['format']
    url = fix_shorts_url(url)

    unique_id = str(uuid.uuid4())
    output_template = os.path.join(DOWNLOAD_FOLDER, f'{unique_id}.%(ext)s')

    # ফরম্যাট সিলেকশন লজিক
    if format_id == 'best':
        ydl_format = 'bestvideo+bestaudio/best'
    elif format_id == 'mp3':
        ydl_format = 'bestaudio/best'
    elif '+bestaudio' in format_id:
        ydl_format = format_id  # already merged format
    else:
        ydl_format = f'bestvideo[format_id={format_id}]+bestaudio/best'
    
    ydl_opts = {
        'outtmpl': output_template,
        'format': ydl_format,
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'extractaudio': False,
        'noplaylist': True,
    }
    
    # কুকি ফাইল থাকলে ব্যবহার করবে
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        ydl_opts['cookiefile'] = COOKIES_FILE
    
    # MP3 এর জন্য পোস্ট-প্রসেসিং
    if format_id == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'extractaudio': True,
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # MP3 হলে এক্সটেনশন চেঞ্জ
            if format_id == 'mp3':
                filename = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3').replace('.mp4', '.mp3')
            
            return send_file(filename, as_attachment=True, download_name=os.path.basename(filename))
            
    except Exception as e:
        return f"""
        <div style="text-align: center; padding: 50px;">
            <h3 style="color: red;">❌ Download failed: {str(e)}</h3>
            <p>Try selecting a different format or check the URL</p>
            <a href='/' style="display: inline-block; margin-top: 20px; padding: 10px 20px; background: #4CAF50; color: white; text-decoration: none; border-radius: 5px;">Go Back</a>
        </div>
        """
    
    finally:
        # ডাউনলোড শেষে temporary ফাইল ডিলিট করা
        try:
            if 'filename' in locals():
                if os.path.exists(filename):
                    os.remove(filename)
        except:
            pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)  # Production এ debug=False