from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import re

app = Flask(__name__)
# Kích hoạt CORS để Stremio có thể giao tiếp với Addon
CORS(app)

# Dựa theo cấu trúc thông thường của KKPhim / Ophim CMS API
API_BASE_URL = "https://phimapi.com"
IMAGE_BASE_URL = "https://phimapi.com/hh/1200x800/"  # Tuỳ chỉnh nếu có domain ảnh riêng

def strip_html(text):
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text)

@app.route('/')
def index():
    return "KKPhim Stremio Addon is running! Thêm URL /manifest.json vào Stremio để sử dụng."

# 1. ENDPOINT: /manifest.json
@app.route('/manifest.json')
def get_manifest():
    return jsonify({
        "id": "com.kkphim.stremio.addon",
        "version": "1.0.0",
        "name": "KKPhim VN",
        "description": "Addon xem phim Việt Nam và Quốc Tế từ nguồn KKPhim.",
        "logo": "https://kkphim.com/uploads/logo-UdZ3lyzQ.png",
        "resources": ["catalog", "meta", "stream"],
        "types": ["movie", "series"],
        "catalogs": [
            {"type": "movie", "id": "kkp_phim_le", "name": "KKPhim - Phim Lẻ"},
            {"type": "series", "id": "kkp_phim_bo", "name": "KKPhim - Phim Bộ"},
            {"type": "series", "id": "kkp_hoat_hinh", "name": "KKPhim - Hoạt Hình"}
        ],
        "idPrefixes": ["kkp_"]
    })

# 2. ENDPOINT: /catalog/<type>/<id>.json
@app.route('/catalog/<type>/<id>.json')
@app.route('/catalog/<type>/<id>/skip=<skip>.json')
def get_catalog(type, id, skip=0):
    page = (int(skip) // 20) + 1 if skip else 1
    
    # Map catalog id với endpoint danh sách của API
    slug_map = {
        "kkp_phim_le": "phim-le",
        "kkp_phim_bo": "phim-bo",
        "kkp_hoat_hinh": "hoat-hinh"
    }
    
    list_slug = slug_map.get(id, "phim-moi-cap-nhat")
    url = f"{API_BASE_URL}/v1/api/danh-sach/{list_slug}?page={page}"
    
    metas = []
    try:
        resp = requests.get(url, timeout=10).json()
        items = resp.get('data', {}).get('items', [])
        
        for item in items:
            item_type = "series" if item.get('type') == 'series' or id == "kkp_phim_bo" else "movie"
            
            poster_url = item.get('thumb_url', '')
            if not poster_url.startswith('http'):
                # Domain ảnh có thể khác nhau tùy cấu hình CMS
                poster_url = f"https://phimimg.com/{poster_url}" 
                
            metas.append({
                "id": f"kkp_{item['slug']}",
                "type": item_type,
                "name": item.get('name', ''),
                "poster": poster_url,
                "description": item.get('origin_name', ''),
                "releaseInfo": str(item.get('year', ''))
            })
    except Exception as e:
        print("Error fetching catalog:", e)
        
    return jsonify({"metas": metas})

# 3. ENDPOINT: /meta/<type>/<id>.json
@app.route('/meta/<type>/<id>.json')
def get_meta(type, id):
    if not id.startswith('kkp_'):
        return jsonify({"meta": {}})
        
    slug = id.split(':')[0].replace('kkp_', '')
    url = f"{API_BASE_URL}/phim/{slug}"
    
    try:
        resp = requests.get(url, timeout=10).json()
        movie = resp.get('movie', {})
        episodes = resp.get('episodes', [])
        
        poster_url = movie.get('thumb_url', '')
        background_url = movie.get('poster_url', '')
        if not poster_url.startswith('http'):
            poster_url = f"https://phimimg.com/{poster_url}"
        if not background_url.startswith('http'):
            background_url = f"https://phimimg.com/{background_url}"
            
        meta = {
            "id": id,
            "type": type,
            "name": movie.get('name', ''),
            "poster": poster_url,
            "background": background_url,
            "description": strip_html(movie.get('content', '')),
            "releaseInfo": str(movie.get('year', '')),
            "genres": [g['name'] for g in movie.get('category', [])],
            "director": [movie.get('director', [])] if isinstance(movie.get('director'), str) else movie.get('director', []),
            "cast": movie.get('actor', []),
        }

        # Xử lý cho Phim Bộ (Series) -> Add Video/Episode list
        if type == "series" and episodes:
            server_data = episodes[0].get('server_data', [])
            videos = []
            for ep in server_data:
                # KKP ID format cho tập phim: kkp_{slug}:season:episode
                ep_num = ep.get('name', '1')
                try:
                    ep_idx = int(re.search(r'\d+', ep_num).group())
                except:
                    ep_idx = 1

                videos.append({
                    "id": f"{id}:1:{ep_idx}",
                    "title": f"Tập {ep_num}",
                    "season": 1,
                    "episode": ep_idx
                })
            meta['videos'] = videos

        return jsonify({"meta": meta})
    except Exception as e:
        print("Error fetching meta:", e)
        return jsonify({"meta": {}})

# 4. ENDPOINT: /stream/<type>/<id>.json
@app.route('/stream/<type>/<id>.json')
def get_stream(type, id):
    if not id.startswith('kkp_'):
        return jsonify({"streams": []})
        
    parts = id.split(':')
    slug = parts[0].replace('kkp_', '')
    target_ep = str(parts[2]) if len(parts) > 2 else "1"
    
    streams = []
    
    # 1. LẤY LINK TỪ KKPHIM
    try:
        kk_url = f"{API_BASE_URL}/phim/{slug}"
        resp = requests.get(kk_url, timeout=5).json()
        episodes = resp.get('episodes', [])
        for server in episodes:
            server_name = server.get('server_name', 'VIP')
            for ep in server.get('server_data', []):
                ep_num_str = str(ep.get('name', '1'))
                try:
                    extracted_num = str(int(re.search(r'\d+', ep_num_str).group()))
                except:
                    extracted_num = "1"
                
                if extracted_num == target_ep or type == "movie":
                    if ep.get('link_m3u8'):
                        streams.append({
                            "title": f"🎬 KKPhim [{server_name}]\n{ep.get('name', 'Full')}",
                            "url": ep.get('link_m3u8'),
                            "behaviorHints": {"bingeGroup": f"kkphim-{server_name}"}
                        })
                    if type == "movie": break
    except Exception as e:
        print("Lỗi lấy KKPhim:", e)

    # 2. LẤY LINK TỪ NGUONC
    try:
        nguonc_url = f"https://phim.nguonc.com/api/film/{slug}"
        resp_nc = requests.get(nguonc_url, timeout=5).json()
        episodes_nc = resp_nc.get('movie', {}).get('episodes', [])
        for server in episodes_nc:
            server_name = server.get('server_name', 'VIP')
            for ep in server.get('items', []):
                ep_num_str = str(ep.get('name', '1'))
                try:
                    extracted_num = str(int(re.search(r'\d+', ep_num_str).group()))
                except:
                    extracted_num = "1"
                
                if extracted_num == target_ep or type == "movie":
                    if ep.get('m3u8'):
                        streams.append({
                            "title": f"🔥 NguonC [{server_name}]\n{ep.get('name', 'Full')}",
                            "url": ep.get('m3u8'),
                            "behaviorHints": {"bingeGroup": f"nguonc-{server_name}"}
                        })
                    if type == "movie": break
    except Exception as e:
        print("Lỗi lấy NguonC:", e)
        
    return jsonify({"streams": streams})

if __name__ == '__main__':
    # Chạy server tại cổng 8080
    app.run(host='0.0.0.0', port=8080, debug=True)
