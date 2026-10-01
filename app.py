from flask import Flask, render_template, send_from_directory, request, jsonify, make_response, Response, abort
import os
import json
import datetime
import html
import urllib.parse
import markdown
import sqlite3
import hashlib
import secrets
import requests
import threading
import uuid
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.fenced_code import FencedCodeExtension
import mdx_math
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

# 配置反向代理支持
# 设置代理服务器的数量（根据实际反向代理层数调整）
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# 获取真实客户端IP的函数
def get_real_client_ip():
    """获取真实客户端IP地址，支持反向代理环境"""
    # 优先从X-Forwarded-For头获取IP
    if request.headers.get('X-Forwarded-For'):
        # X-Forwarded-For格式：client, proxy1, proxy2
        ips = request.headers.get('X-Forwarded-For', '').split(',')
        # 取第一个非空IP（即客户端IP）
        for ip in ips:
            ip = ip.strip()
            if ip and ip != 'unknown':
                return ip
    
    # 其次从X-Real-IP头获取
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    
    # 最后使用远程地址
    return request.remote_addr

# Markdown处理函数
def process_markdown_content(markdown_content):
    """处理Markdown内容，支持自定义符号和扩展功能"""
    # 预处理：处理自定义颜色和背景色控制符
    def process_color_controls(text):
        # 定义特殊颜色代码映射
        color_map = {
            'NONE': 'inherit',  # 恢复默认颜色
            'R': '#FF0000',     # 红色
            'G': '#00FF00',     # 绿色
            'B': '#0000FF',     # 蓝色
            'Y': '#FFFF00',     # 黄色
            'P': '#FFC0CB',     # 粉色
            'U': '#800080',     # 紫色
            'K': '#000000'      # 黑色
        }
        
        # 辅助函数：计算颜色的反色
        def invert_color(hex_color):
            """计算颜色的反色，用于描边默认颜色"""
            if not hex_color or hex_color == 'inherit':
                return '#FFFFFF'  # 默认白色描边
            # 移除 # 号
            hex_color = hex_color.lstrip('#')
            # 解析 RGB
            r = 255 - int(hex_color[0:2], 16)
            g = 255 - int(hex_color[2:4], 16)
            b = 255 - int(hex_color[4:6], 16)
            return f'#{r:02X}{g:02X}{b:02X}'
        
        # 辅助函数：解析图片控制符参数
        def parse_image_params(params_str):
            """解析图片控制符参数: f:路径|s:x大小,y大小"""
            params = {'file': None, 'size': None}
            parts = params_str.split('|')
            for part in parts:
                part = part.strip()
                if part.startswith('f:'):
                    params['file'] = part[2:].strip()
                elif part.startswith('s:'):
                    size_str = part[2:].strip()
                    if ',' in size_str:
                        w, h = size_str.split(',')
                        params['size'] = (w.strip(), h.strip())
                    else:
                        params['size'] = (size_str, None)
            return params
        
        # 辅助函数：解析描边控制符参数
        def parse_stroke_params(params_str):
            """解析描边控制符参数: o:大小|c:颜色"""
            params = {'width': None, 'color': None}
            parts = params_str.split('|')
            for part in parts:
                part = part.strip()
                if part.startswith('o:'):
                    try:
                        params['width'] = float(part[2:].strip())
                    except ValueError:
                        pass
                elif part.startswith('c:'):
                    color_code = part[2:].strip()
                    if color_code in color_map:
                        params['color'] = color_map[color_code]
                    elif len(color_code) == 6 and all(c in '0123456789ABCDEFabcdef' for c in color_code):
                        params['color'] = f'#{color_code.upper()}'
            return params
        
        # 辅助函数：为每个字符添加旋转样式
        def apply_rotation_to_text(text, angle, styles=None):
            """为每个字符添加旋转效果，同时保持其他样式"""
            if not text:
                return ''
            style_str = ''
            if styles:
                style_str = '; '.join(styles) + '; '
            chars = []
            for char in text:
                if char == ' ':
                    chars.append(f'<span style="{style_str}display: inline-block; transform: rotate({angle}deg);">&nbsp;</span>')
                else:
                    chars.append(f'<span style="{style_str}display: inline-block; transform: rotate({angle}deg);">{char}</span>')
            return ''.join(chars)
        
        # 处理颜色控制符
        lines = text.split('\n')
        processed_lines = []
        
        for line in lines:
            # 跳过代码块中的内容
            if line.strip().startswith('```'):
                processed_lines.append(line)
                continue
            
            # 处理颜色、背景色、描边、旋转和粗细控制符
            parts = []
            current_pos = 0
            current_color = None
            current_background = None
            current_stroke = None  # 描边宽度
            current_stroke_color = None  # 描边颜色（None 表示使用反色）
            current_rotation = None  # 旋转角度
            current_weight = None  # 文字粗细
            
            while current_pos < len(line):
                # 查找下一个控制符（%、°）
                percent_pos = line.find('%', current_pos)
                degree_pos = line.find('°', current_pos)
                
                # 确定下一个控制符的位置和类型
                start_pos = -1
                control_type = None
                
                if percent_pos != -1 and degree_pos != -1:
                    if percent_pos < degree_pos:
                        start_pos = percent_pos
                        control_type = 'percent'
                    else:
                        start_pos = degree_pos
                        control_type = 'degree'
                elif percent_pos != -1:
                    start_pos = percent_pos
                    control_type = 'percent'
                elif degree_pos != -1:
                    start_pos = degree_pos
                    control_type = 'degree'
                
                if start_pos == -1:
                    # 没有更多控制符，添加剩余文本
                    remaining_text = line[current_pos:]
                    if remaining_text:
                        # 应用当前的样式设置
                        styles = []
                        if current_color:
                            styles.append(f'color: {current_color}')
                        if current_background:
                            styles.append(f'background-color: {current_background}')
                        if current_stroke:
                            stroke_color = current_stroke_color if current_stroke_color else invert_color(current_color)
                            styles.append(f'-webkit-text-stroke: {current_stroke}px {stroke_color}')
                        if current_weight:
                            styles.append(f'font-weight: {current_weight}')
                        
                        if current_rotation is not None:
                            parts.append(apply_rotation_to_text(remaining_text, current_rotation, styles if styles else None))
                        elif styles:
                            style_str = '; '.join(styles)
                            parts.append(f'<span style="{style_str}">{remaining_text}</span>')
                        else:
                            parts.append(remaining_text)
                    break
                
                # 添加控制符前的文本
                if current_pos < start_pos:
                    text_before = line[current_pos:start_pos]
                    if text_before:
                        # 应用当前的样式设置
                        styles = []
                        if current_color:
                            styles.append(f'color: {current_color}')
                        if current_background:
                            styles.append(f'background-color: {current_background}')
                        if current_stroke:
                            stroke_color = current_stroke_color if current_stroke_color else invert_color(current_color)
                            styles.append(f'-webkit-text-stroke: {current_stroke}px {stroke_color}')
                        if current_weight:
                            styles.append(f'font-weight: {current_weight}')
                        
                        if current_rotation is not None:
                            parts.append(apply_rotation_to_text(text_before, current_rotation, styles if styles else None))
                        elif styles:
                            style_str = '; '.join(styles)
                            parts.append(f'<span style="{style_str}">{text_before}</span>')
                        else:
                            parts.append(text_before)
                
                if control_type == 'degree':
                    # 背景色控制符 °XXX°
                    end_pos = line.find('°', start_pos + 1)
                    if end_pos == -1:
                        parts.append(line[start_pos:])
                        break
                    
                    color_code = line[start_pos + 1:end_pos]
                    if color_code in color_map:
                        color_value = color_map[color_code]
                    elif len(color_code) == 6 and all(c in '0123456789ABCDEFabcdef' for c in color_code):
                        color_value = f'#{color_code.upper()}'
                    else:
                        parts.append(line[start_pos:end_pos + 1])
                        current_pos = end_pos + 1
                        continue
                    
                    current_background = color_value if color_value != 'inherit' else None
                    current_pos = end_pos + 1
                else:
                    # 百分号控制符 %XXX%
                    end_pos = line.find('%', start_pos + 1)
                    if end_pos == -1:
                        parts.append(line[start_pos:])
                        break
                    
                    control_code = line[start_pos + 1:end_pos]
                    
                    # 检查是否是图片控制符 %p ... %
                    if control_code.startswith('p '):
                        params_str = control_code[2:].strip()
                        img_params = parse_image_params(params_str)
                        if img_params['file']:
                            img_src = img_params['file']
                            size_attr = ''
                            if img_params['size']:
                                w, h = img_params['size']
                                if h:
                                    size_attr = f' width="{w}" height="{h}"'
                                else:
                                    size_attr = f' width="{w}"'
                            parts.append(f'<img src="{img_src}" alt="" style="display: inline-block; vertical-align: middle;"{size_attr}>')
                        current_pos = end_pos + 1
                        continue
                    
                    # 检查是否是描边控制符 %f o:大小|c:颜色%
                    if control_code.startswith('f '):
                        stroke_params_str = control_code[2:].strip()
                        if stroke_params_str == 'NONE' or 'NONE' in stroke_params_str:
                            current_stroke = None
                            current_stroke_color = None
                        else:
                            stroke_params = parse_stroke_params(stroke_params_str)
                            if stroke_params['width']:
                                current_stroke = stroke_params['width']
                                current_stroke_color = stroke_params['color']
                        current_pos = end_pos + 1
                        continue

                    # 检查是否是粗细控制符 %c s:数字%
                    if control_code.startswith('c '):
                        weight_params = control_code[2:].strip()
                        if weight_params == 'NONE' or 'NONE' in weight_params:
                            current_weight = None
                        elif weight_params.startswith('s:'):
                            try:
                                weight = weight_params[2:].strip()
                                current_weight = weight
                            except ValueError:
                                pass
                        current_pos = end_pos + 1
                        continue

                    # 检查是否是旋转控制符 %r a:数字%
                    if control_code.startswith('r '):
                        rotation_params = control_code[2:].strip()
                        if rotation_params.startswith('a:'):
                            try:
                                angle = float(rotation_params[2:])
                                current_rotation = angle
                            except ValueError:
                                pass
                        elif rotation_params == 'NONE' or 'NONE' in rotation_params:
                            current_rotation = None
                        current_pos = end_pos + 1
                        continue
                    
                    # 颜色控制符
                    if control_code in color_map:
                        # NONE 特殊处理：重置所有样式
                        if control_code == 'NONE':
                            current_color = None
                            current_stroke = None
                            current_stroke_color = None
                            current_rotation = None
                            current_weight = None
                        else:
                            color_value = color_map[control_code]
                            current_color = color_value if color_value != 'inherit' else None
                        current_pos = end_pos + 1
                        continue
                    elif len(control_code) == 6 and all(c in '0123456789ABCDEFabcdef' for c in control_code):
                        color_value = f'#{control_code.upper()}'
                        current_color = color_value
                        current_pos = end_pos + 1
                        continue
                    else:
                        # 无效控制符，保持原样
                        parts.append(line[start_pos:end_pos + 1])
                        current_pos = end_pos + 1
                        continue
            
            processed_lines.append(''.join(parts))
        
        return '\n'.join(processed_lines)
    
    # 先处理颜色控制符
    processed_content = process_color_controls(markdown_content)
    
    # 转换Markdown为HTML，添加代码高亮、数学公式和文本格式支持
    extensions = [
        FencedCodeExtension(),
        CodeHiliteExtension(
            css_class='highlight',
            linenums=False,
            guess_lang=True
        ),
        'mdx_math',
        'markdown.extensions.attr_list',  # 属性列表支持
        'markdown.extensions.tables',     # 表格支持
        'markdown.extensions.footnotes',  # 脚注支持
        'markdown.extensions.toc',        # 目录支持
        'markdown.extensions.smarty',     # 智能标点符号
        'markdown.extensions.admonition', # 警告框支持
        'markdown.extensions.nl2br',      # 换行转<br>
        'markdown.extensions.sane_lists', # 智能列表
        'markdown.extensions.extra'       # 额外功能（包含删除线等）
    ]
    
    extension_configs = {
        'mdx_math': {
            'enable_dollar_delimiter': True,
            'add_preview': True
        }
    }
    
    html_content = markdown.markdown(processed_content, extensions=extensions, extension_configs=extension_configs)
    
    # 后处理：处理特殊附件链接
    def process_download_links(html_content):
        import re
        
        # 匹配附件链接模式：[dltag:文件名](下载地址)
        pattern = r'<p>\s*<a href="([^"]+)">dltag:([^<]+)</a>\s*</p>'
        
        def replace_download_link(match):
            download_url = match.group(1)
            filename = match.group(2)
            
            # 转义 URL 和文件名
            escaped_url = html.escape(download_url)
            escaped_filename = html.escape(filename)
            
            # 生成附件容器HTML
            return f'''
<div class="download-attachment">
    <div class="attachment-info">
        <span class="filename">{escaped_filename}</span>
        <div class="attachment-actions">
            <button class="info-button" data-url="{escaped_url}">查看信息</button>
            <button class="download-button" onclick="window.open('{escaped_url}', '_blank')" title="下载附件">下载</button>
        </div>
    </div>
    <div class="attachment-details" hidden></div>
</div>
            '''
        
        # 替换附件链接
        processed_html = re.sub(pattern, replace_download_link, html_content)
        return processed_html
    
    # 应用附件链接处理
    html_content = process_download_links(html_content)
    
    return html_content

# 获取博客设置的函数
def get_blog_settings():
    """读取博客配置文件，返回博客设置"""
    settings_path = os.path.join(os.path.dirname(__file__), 'blogsettings.json')
    default_settings = {'blogname': "manyJ'sBlog"}
    
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            return {**default_settings, **settings}
        except Exception as e:
            print(f"读取博客设置失败: {e}")
            return default_settings
    return default_settings

# 读取博客配置
def load_blog_settings():
    """读取博客配置项"""
    settings_path = os.path.join(os.path.dirname(__file__), 'blogsettings.json')
    try:
        if os.path.exists(settings_path):
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                return {
                    'close_comment': settings.get('close_comment', False),
                    'blogname': settings.get('blogname', '请在blogsettings.json中设置博客名称'),
                    'blognamestart': settings.get('blognamestart', '请在blogsettings.json中设置博客名称'),
                    'headerlightcount': settings.get('headerlightcount', 1),
                    'author_name': settings.get('author_name', '请在blogsettings.json中设置作者名称')
                }
    except Exception as e:
        print(f"读取博客配置失败: {e}")
    return {
        'close_comment': False,
        'blogname': '请在blogsettings.json中设置博客名称',
        'blognamestart': '请在blogsettings.json中设置博客名称',
        'headerlightcount': 1,
        'author_name': '请在blogsettings.json中设置作者名称'
    }

# 全局变量：博客配置
BLOG_SETTINGS = load_blog_settings()
CLOSE_COMMENT = BLOG_SETTINGS['close_comment']

# 博客文章目录
BLOG_DIR = os.path.join(os.path.dirname(__file__), 'blogs')

# RSS 缓存数据
rss_articles_cache = []
rss_cache_lock = threading.Lock()
rss_timer = None

# MD5 计算缓存和锁
_md5_cache = {}  # {file_path: {"status": "calculating"/"done", "md5": "xxx"}}
_md5_calculating = set()  # 正在计算的文件路径集合
_md5_lock = threading.Lock()

def stop_rss_cache():
    """停止RSS缓存刷新线程"""
    global rss_timer
    if rss_timer:
        rss_timer.cancel()

def _calculate_md5_thread(file_path, cache_key):
    """后台线程计算文件 MD5"""
    try:
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        md5_value = hasher.hexdigest()
        
        with _md5_lock:
            _md5_cache[cache_key] = {"status": "done", "md5": md5_value}
            _md5_calculating.discard(cache_key)
    except Exception as e:
        with _md5_lock:
            _md5_cache[cache_key] = {"status": "error", "error": str(e)}
            _md5_calculating.discard(cache_key)


def remove_color_controls(text):
    """去除颜色控制符"""
    import re
    # 去除 %颜色代码% 和 °颜色代码° 格式的控制符
    # 处理 %颜色代码% 格式
    text = re.sub(r'%[^%\n]+%', '', text)
    # 处理 °颜色代码° 格式
    text = re.sub(r'°[^°\n]+°', '', text)
    return text

def get_all_articles_for_rss():
    """获取所有文章用于RSS订阅，与blog_list排序逻辑一致"""
    articles = []
    categories = []
    
    if os.path.exists(BLOG_DIR):
        for category_dir in os.listdir(BLOG_DIR):
            category_path = os.path.join(BLOG_DIR, category_dir)
            if os.path.isdir(category_path):
                categories.append(category_dir)
    
    category_order = {}
    category_json_path = os.path.join(BLOG_DIR, 'category.json')
    if os.path.exists(category_json_path):
        try:
            with open(category_json_path, 'r', encoding='utf-8') as f:
                category_order = json.load(f)
        except Exception as e:
            print(f"读取分类排序配置失败: {e}")
    
    def get_category_order(category_name):
        return category_order.get(category_name, float('inf'))
    
    categories.sort(key=get_category_order)
    
    for cat in categories:
        category_path = os.path.join(BLOG_DIR, cat)
        if os.path.exists(category_path):
            cat_order = {}
            category_json_path = os.path.join(category_path, 'blog_category.json')
            if os.path.exists(category_json_path):
                try:
                    with open(category_json_path, 'r', encoding='utf-8') as f:
                        cat_order = json.load(f)
                except Exception as e:
                    print(f"读取分类文章排序配置失败 {cat}: {e}")
            
            for article_dir in os.listdir(category_path):
                article_path = os.path.join(category_path, article_dir)
                if os.path.isdir(article_path):
                    config_path = os.path.join(article_path, 'config.json')
                    if os.path.exists(config_path):
                        try:
                            with open(config_path, 'r', encoding='utf-8') as f:
                                config = json.load(f)
                            
                            # 读取文章完整内容
                            blog_md_path = os.path.join(article_path, 'blog.md')
                            content = ''
                            if os.path.exists(blog_md_path):
                                try:
                                    with open(blog_md_path, 'r', encoding='utf-8') as f:
                                        content = f.read()
                                    # 去除颜色控制符
                                    content = remove_color_controls(content)
                                except Exception as e:
                                    print(f"读取文章内容失败 {cat}/{article_dir}: {e}")
                            
                            pub_date = None
                            if 'pub_date' in config:
                                try:
                                    pub_date = datetime.datetime.fromisoformat(config['pub_date'])
                                except:
                                    pub_date = datetime.datetime.now()
                            else:
                                # 使用blog.md文件的修改日期
                                try:
                                    if os.path.exists(blog_md_path):
                                        stat_info = os.stat(blog_md_path)
                                        pub_date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                                    else:
                                        stat_info = os.stat(article_path)
                                        pub_date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                                except:
                                    pub_date = datetime.datetime.now()
                            
                            articles.append({
                                'id': article_dir,
                                'category': cat,
                                'title': config.get('title', '无标题'),
                                'description': content,  # 使用完整内容作为description
                                'order': cat_order.get(article_dir, float('inf')),
                                'category_order': get_category_order(cat),
                                'pub_date': pub_date.strftime('%Y-%m-%d') if pub_date else '',
                                'pub_date_full': pub_date
                            })
                        except Exception as e:
                            print(f"读取文章配置失败 {cat}/{article_dir}: {e}")
    
    # RSS订阅显示所有文章，按修改日期排序（最新的在前）
    def get_pub_date_order(article):
        pub_date = article.get('pub_date')
        if not pub_date:
            return datetime.datetime.min
        if isinstance(pub_date, str):
            # 字符串格式的日期，直接返回字符串用于排序
            return pub_date
        return pub_date
    
    articles.sort(key=get_pub_date_order, reverse=True)
    
    for article in articles:
        # 优先使用pub_date_full（完整的datetime对象）
        pub_date_full = article.get('pub_date_full')
        if pub_date_full:
            article['pub_date_str'] = pub_date_full.strftime('%a, %d %b %Y %H:%M:%S +0800')
        elif article['pub_date']:
            # 兼容：pub_date可能是字符串或datetime对象
            if isinstance(article['pub_date'], str):
                # 字符串格式，转换为datetime再生成RFC 822格式
                try:
                    dt = datetime.datetime.strptime(article['pub_date'], '%Y-%m-%d')
                    article['pub_date_str'] = dt.strftime('%a, %d %b %Y %H:%M:%S +0800')
                except:
                    article['pub_date_str'] = article['pub_date']
            else:
                article['pub_date_str'] = article['pub_date'].strftime('%a, %d %b %Y %H:%M:%S +0800')
        else:
            article['pub_date_str'] = datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0800')
    
    return articles

def refresh_rss_cache():
    """刷新RSS缓存"""
    global rss_articles_cache, rss_timer
    articles = get_all_articles_for_rss()
    with rss_cache_lock:
        rss_articles_cache = articles
    rss_timer = threading.Timer(60, refresh_rss_cache)
    rss_timer.daemon = True
    rss_timer.start()

# 只在主进程中启动RSS缓存刷新，避免重载时重复启动
# 通过检查环境变量来判断是否为主进程
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    refresh_rss_cache()

def shutdown_rss_cache():
    """Flask应用关闭时停止RSS缓存刷新"""
    stop_rss_cache()

@app.route('/')
def index():
    """首页 - 显示文章列表，这个skip_welcome不要改成False，懒得移除了就这么补吧，啊啊啊啊啊啊啊啊啊"""
    settings = get_blog_settings()
    return render_template('index.html', 
                          skip_welcome=True, 
                          blogname=settings['blogname'],
                          blognamestart=settings['blognamestart'],
                          headerlightcount=settings['headerlightcount'])

@app.route('/api/friendly_links')
@app.route('/friendly_links.json')  # 旧接口兼容
def friendly_links():
    """提供友情链接数据"""
    friendly_links_path = os.path.join(os.path.dirname(__file__), 'friendly_links.json')
    
    if os.path.exists(friendly_links_path):
        try:
            with open(friendly_links_path, 'r', encoding='utf-8') as f:
                links_data = json.load(f)
            return links_data
        except Exception as e:
            print(f"读取友情链接文件失败: {e}")
            return {}
    else:
        return {}

@app.route('/archive')
def archive():
    """归档页面"""
    settings = get_blog_settings()
    return render_template('archive.html',
                          blogname=settings['blogname'],
                          blognamestart=settings['blognamestart'],
                          headerlightcount=settings['headerlightcount'])

@app.route('/api/articles/dates')
def get_articles_dates():
    """获取所有文章的日期信息"""
    articles = []
    
    if os.path.exists(BLOG_DIR):
        for cat in os.listdir(BLOG_DIR):
            category_path = os.path.join(BLOG_DIR, cat)
            if os.path.isdir(category_path):
                for article_dir in os.listdir(category_path):
                    article_path = os.path.join(category_path, article_dir)
                    if os.path.isdir(article_path):
                        config_path = os.path.join(article_path, 'config.json')
                        if os.path.exists(config_path):
                            try:
                                with open(config_path, 'r', encoding='utf-8') as f:
                                    config = json.load(f)
                                
                                pub_date = None
                                if 'pub_date' in config:
                                    try:
                                        pub_date = datetime.datetime.fromisoformat(config['pub_date'])
                                    except:
                                        pub_date = datetime.datetime.now()
                                else:
                                    blog_md_path = os.path.join(article_path, 'blog.md')
                                    try:
                                        if os.path.exists(blog_md_path):
                                            stat_info = os.stat(blog_md_path)
                                            pub_date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                                        else:
                                            stat_info = os.stat(article_path)
                                            pub_date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                                    except:
                                        pub_date = datetime.datetime.now()
                                
                                if pub_date:
                                    articles.append({
                                        'year': pub_date.year,
                                        'month': pub_date.month,
                                        'day': pub_date.day
                                    })
                            except Exception as e:
                                print(f"读取文章配置失败 {cat}/{article_dir}: {e}")
    
    return jsonify({'dates': articles})

@app.route('/api/articles/filter')
def filter_articles():
    """根据日期筛选文章"""
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    day = request.args.get('day', type=int)
    
    articles = []
    categories = []
    
    if os.path.exists(BLOG_DIR):
        for cat in os.listdir(BLOG_DIR):
            category_path = os.path.join(BLOG_DIR, cat)
            if os.path.isdir(category_path):
                categories.append(cat)
        
        category_order = {}
        category_json_path = os.path.join(BLOG_DIR, 'category.json')
        if os.path.exists(category_json_path):
            try:
                with open(category_json_path, 'r', encoding='utf-8') as f:
                    category_order = json.load(f)
            except Exception as e:
                print(f"读取分类排序配置失败: {e}")
        
        def get_category_order(category_name):
            return category_order.get(category_name, float('inf'))
        
        categories.sort(key=get_category_order)
        
        for cat in categories:
            category_path = os.path.join(BLOG_DIR, cat)
            
            cat_order = {}
            category_json_path = os.path.join(category_path, 'blog_category.json')
            if os.path.exists(category_json_path):
                try:
                    with open(category_json_path, 'r', encoding='utf-8') as f:
                        cat_order = json.load(f)
                except Exception as e:
                    print(f"读取分类文章排序配置失败 {cat}: {e}")
            
            for article_dir in os.listdir(category_path):
                article_path = os.path.join(category_path, article_dir)
                if os.path.isdir(article_path):
                    config_path = os.path.join(article_path, 'config.json')
                    if os.path.exists(config_path):
                        try:
                            with open(config_path, 'r', encoding='utf-8') as f:
                                config = json.load(f)
                            
                            icon_path = os.path.join(article_path, 'icon.png')
                            has_icon = os.path.exists(icon_path)
                            
                            pub_date = None
                            if 'pub_date' in config:
                                try:
                                    pub_date = datetime.datetime.fromisoformat(config['pub_date'])
                                except:
                                    pub_date = datetime.datetime.now()
                            else:
                                blog_md_path = os.path.join(article_path, 'blog.md')
                                try:
                                    if os.path.exists(blog_md_path):
                                        stat_info = os.stat(blog_md_path)
                                        pub_date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                                    else:
                                        stat_info = os.stat(article_path)
                                        pub_date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                                except:
                                    pub_date = datetime.datetime.now()
                            
                            should_include = True
                            if year and pub_date:
                                if pub_date.year != year:
                                    should_include = False
                                elif month and pub_date.month != month:
                                    should_include = False
                                elif day and pub_date.day != day:
                                    should_include = False
                            
                            if should_include and pub_date:
                                articles.append({
                                    'id': article_dir,
                                    'category': cat,
                                    'title': config.get('title', '无标题'),
                                    'small_title': config.get('small_title', '无简介'),
                                    'has_icon': has_icon,
                                    'order': cat_order.get(article_dir, float('inf')),
                                    'category_order': get_category_order(cat),
                                    'pub_date': pub_date.strftime('%Y-%m-%d') if pub_date else ''
                                })
                        except Exception as e:
                            print(f"读取文章配置失败 {cat}/{article_dir}: {e}")
    
    def get_pub_date_order(article):
        pub_date = article.get('pub_date')
        if not pub_date:
            return ''
        return pub_date
    
    articles.sort(key=get_pub_date_order, reverse=True)
    
    return jsonify({'articles': articles})

@app.route('/api/blog')
@app.route('/api/blog/<category>')
@app.route('/blog')  # 旧接口兼容
@app.route('/blog/<category>')
def blog_list(category=None):
    """获取文章列表数据"""
    articles = []
    categories = []
    
    # 获取所有分类
    if os.path.exists(BLOG_DIR):
        for category_dir in os.listdir(BLOG_DIR):
            category_path = os.path.join(BLOG_DIR, category_dir)
            if os.path.isdir(category_path):
                categories.append(category_dir)
    
    # 读取分类排序配置
    category_order = {}
    category_json_path = os.path.join(BLOG_DIR, 'category.json')
    if os.path.exists(category_json_path):
        try:
            with open(category_json_path, 'r', encoding='utf-8') as f:
                category_order = json.load(f)
        except Exception as e:
            print(f"读取分类排序配置失败: {e}")
    
    # 根据category.json中的顺序对分类进行排序
    def get_category_order(category_name):
        return category_order.get(category_name, float('inf'))
    
    categories.sort(key=get_category_order)
    
    # 如果没有指定分类或指定为"全部"，获取所有分类的文章
    if not category or category == '全部':
        # 遍历所有分类获取文章
        for cat in categories:
            category_path = os.path.join(BLOG_DIR, cat)
            if os.path.exists(category_path):
                # 读取分类下的文章排序配置
                cat_order = {}
                category_json_path = os.path.join(category_path, 'blog_category.json')
                if os.path.exists(category_json_path):
                    try:
                        with open(category_json_path, 'r', encoding='utf-8') as f:
                            cat_order = json.load(f)
                    except Exception as e:
                        print(f"读取分类文章排序配置失败 {cat}: {e}")
                
                for article_dir in os.listdir(category_path):
                    article_path = os.path.join(category_path, article_dir)
                    if os.path.isdir(article_path):
                        # 读取配置文件
                        config_path = os.path.join(article_path, 'config.json')
                        if os.path.exists(config_path):
                            try:
                                with open(config_path, 'r', encoding='utf-8') as f:
                                    config = json.load(f)
                                
                                # 检查是否有封面图片
                                icon_path = os.path.join(article_path, 'icon.png')
                                has_icon = os.path.exists(icon_path)
                                
                                # 获取文章修改日期（使用blog.md文件的修改日期）
                                pub_date = None
                                if 'pub_date' in config:
                                    try:
                                        pub_date = datetime.datetime.fromisoformat(config['pub_date'])
                                    except:
                                        pub_date = datetime.datetime.now()
                                else:
                                    # 使用blog.md文件的修改日期
                                    blog_md_path = os.path.join(article_path, 'blog.md')
                                    try:
                                        if os.path.exists(blog_md_path):
                                            stat_info = os.stat(blog_md_path)
                                            pub_date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                                        else:
                                            stat_info = os.stat(article_path)
                                            pub_date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                                    except:
                                        pub_date = datetime.datetime.now()
                                
                                articles.append({
                                    'id': article_dir,
                                    'category': cat,
                                    'title': config.get('title', '无标题'),
                                    'small_title': config.get('small_title', '无简介'),
                                    'has_icon': has_icon,
                                    'order': cat_order.get(article_dir, float('inf')),
                                    'category_order': get_category_order(cat),
                                    'pub_date': pub_date.strftime('%Y-%m-%d') if pub_date else '',
                                    'pub_date_full': pub_date
                                })
                            except Exception as e:
                                print(f"读取文章配置失败 {cat}/{article_dir}: {e}")
        
        # "全部"分类按修改日期排序（最新的在前）
        def get_pub_date_order(article):
            pub_date = article.get('pub_date')
            if not pub_date:
                return ''
            return pub_date
        
        articles.sort(key=get_pub_date_order, reverse=True)
        
        # 如果没有指定分类，设置当前分类为"全部"
        if not category:
            category = '全部'
    else:
        # 遍历指定分类的文章目录
        category_path = os.path.join(BLOG_DIR, category)
        if os.path.exists(category_path):
            # 读取分类下的文章排序配置
            cat_order = {}
            category_json_path = os.path.join(category_path, 'blog_category.json')
            if os.path.exists(category_json_path):
                try:
                    with open(category_json_path, 'r', encoding='utf-8') as f:
                        cat_order = json.load(f)
                except Exception as e:
                    print(f"读取分类文章排序配置失败 {category}: {e}")
            
            for article_dir in os.listdir(category_path):
                article_path = os.path.join(category_path, article_dir)
                if os.path.isdir(article_path):
                    # 读取配置文件
                    config_path = os.path.join(article_path, 'config.json')
                    if os.path.exists(config_path):
                        try:
                            with open(config_path, 'r', encoding='utf-8') as f:
                                config = json.load(f)
                            
                            # 检查是否有封面图片
                            icon_path = os.path.join(article_path, 'icon.png')
                            has_icon = os.path.exists(icon_path)
                            
                            # 获取文章修改日期
                            pub_date = None
                            if 'pub_date' in config:
                                try:
                                    pub_date = datetime.datetime.fromisoformat(config['pub_date'])
                                except:
                                    pub_date = datetime.datetime.now()
                            else:
                                # 使用blog.md文件的修改日期
                                blog_md_path = os.path.join(article_path, 'blog.md')
                                try:
                                    if os.path.exists(blog_md_path):
                                        stat_info = os.stat(blog_md_path)
                                        pub_date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                                    else:
                                        stat_info = os.stat(article_path)
                                        pub_date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                                except:
                                    pub_date = datetime.datetime.now()
                            
                            articles.append({
                                'id': article_dir,
                                'category': category,
                                'title': config.get('title', '无标题'),
                                'small_title': config.get('small_title', '无简介'),
                                'has_icon': has_icon,
                                'order': cat_order.get(article_dir, float('inf')),
                                'pub_date': pub_date.strftime('%Y-%m-%d') if pub_date else '',
                                'pub_date_full': pub_date
                            })
                        except Exception as e:
                            print(f"读取文章配置失败 {category}/{article_dir}: {e}")
            
            # 根据blog_category.json中的顺序对文章进行排序
            def get_article_order(article):
                return article.get('order', float('inf'))
            
            articles.sort(key=get_article_order)
    
    return {
        'categories': categories,
        'current_category': category,
        'articles': articles
    }



@app.route('/api/articles/content/<category>/<article_id>')
@app.route('/read/<category>/<article_id>/content')  # 旧接口兼容
def get_article_content(category, article_id):
    """获取文章内容"""
    article_path = os.path.join(BLOG_DIR, category, article_id)
    
    if not os.path.exists(article_path):
        return {'error': '文章不存在'}, 404
    
    # 读取配置
    config_path = os.path.join(article_path, 'config.json')
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            print(f"读取配置失败: {e}")
    
    # 读取Markdown内容
    md_path = os.path.join(article_path, 'blog.md')
    content = ''
    md_content = ''
    update_date = ''
    word_count = 0
    
    if os.path.exists(md_path):
        try:
            # 获取文件修改时间作为更新日期
            update_timestamp = os.path.getmtime(md_path)
            update_date = datetime.datetime.fromtimestamp(update_timestamp).strftime('%Y-%m-%d')
            
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            
            # 预处理：处理自定义颜色和背景色控制符
            def process_color_controls(text):
                # 定义特殊颜色代码映射
                color_map = {
                    'NONE': 'inherit',  # 恢复默认颜色
                    'R': '#FF0000',     # 红色
                    'G': '#00FF00',     # 绿色
                    'B': '#0000FF',     # 蓝色
                    'Y': '#FFFF00',     # 黄色
                    'P': '#FFC0CB',     # 粉色
                    'U': '#800080',     # 紫色
                    'K': '#000000'      # 黑色
                }
                
                # 辅助函数：计算颜色的反色
                def invert_color(hex_color):
                    """计算颜色的反色，用于描边默认颜色"""
                    if not hex_color or hex_color == 'inherit':
                        return '#FFFFFF'
                    hex_color = hex_color.lstrip('#')
                    r = 255 - int(hex_color[0:2], 16)
                    g = 255 - int(hex_color[2:4], 16)
                    b = 255 - int(hex_color[4:6], 16)
                    return f'#{r:02X}{g:02X}{b:02X}'
                
                # 辅助函数：解析图片控制符参数
                def parse_image_params(params_str):
                    params = {'file': None, 'size': None}
                    parts = params_str.split('|')
                    for part in parts:
                        part = part.strip()
                        if part.startswith('f:'):
                            params['file'] = part[2:].strip()
                        elif part.startswith('s:'):
                            size_str = part[2:].strip()
                            if ',' in size_str:
                                w, h = size_str.split(',')
                                params['size'] = (w.strip(), h.strip())
                            else:
                                params['size'] = (size_str, None)
                    return params
                
                # 辅助函数：解析描边控制符参数
                def parse_stroke_params(params_str):
                    params = {'width': None, 'color': None}
                    parts = params_str.split('|')
                    for part in parts:
                        part = part.strip()
                        if part.startswith('o:'):
                            try:
                                params['width'] = float(part[2:].strip())
                            except ValueError:
                                pass
                        elif part.startswith('c:'):
                            color_code = part[2:].strip()
                            if color_code in color_map:
                                params['color'] = color_map[color_code]
                            elif len(color_code) == 6 and all(c in '0123456789ABCDEFabcdef' for c in color_code):
                                params['color'] = f'#{color_code.upper()}'
                    return params
                
                # 辅助函数：为每个字符添加旋转样式
                def apply_rotation_to_text(text, angle, styles=None):
                    if not text:
                        return ''
                    style_str = ''
                    if styles:
                        style_str = '; '.join(styles) + '; '
                    chars = []
                    for char in text:
                        if char == ' ':
                            chars.append(f'<span style="{style_str}display: inline-block; transform: rotate({angle}deg);">&nbsp;</span>')
                        else:
                            chars.append(f'<span style="{style_str}display: inline-block; transform: rotate({angle}deg);">{char}</span>')
                    return ''.join(chars)
                
                # 处理颜色控制符
                lines = text.split('\n')
                processed_lines = []
                
                for line in lines:
                    # 跳过代码块中的内容
                    if line.strip().startswith('```'):
                        processed_lines.append(line)
                        continue
                    
                    # 处理颜色、背景色、描边和旋转控制符
                    parts = []
                    current_pos = 0
                    current_color = None
                    current_background = None
                    current_stroke = None
                    current_stroke_color = None
                    current_rotation = None
                    
                    while current_pos < len(line):
                        # 查找下一个控制符（%、°）
                        percent_pos = line.find('%', current_pos)
                        degree_pos = line.find('°', current_pos)
                        
                        # 确定下一个控制符的位置和类型
                        start_pos = -1
                        control_type = None
                        
                        if percent_pos != -1 and degree_pos != -1:
                            if percent_pos < degree_pos:
                                start_pos = percent_pos
                                control_type = 'percent'
                            else:
                                start_pos = degree_pos
                                control_type = 'degree'
                        elif percent_pos != -1:
                            start_pos = percent_pos
                            control_type = 'percent'
                        elif degree_pos != -1:
                            start_pos = degree_pos
                            control_type = 'degree'
                        
                        if start_pos == -1:
                            remaining_text = line[current_pos:]
                            if remaining_text:
                                styles = []
                                if current_color:
                                    styles.append(f'color: {current_color}')
                                if current_background:
                                    styles.append(f'background-color: {current_background}')
                                if current_stroke:
                                    stroke_color = current_stroke_color if current_stroke_color else invert_color(current_color)
                                    styles.append(f'-webkit-text-stroke: {current_stroke}px {stroke_color}')
                                
                                if current_rotation is not None:
                                    parts.append(apply_rotation_to_text(remaining_text, current_rotation, styles if styles else None))
                                elif styles:
                                    style_str = '; '.join(styles)
                                    parts.append(f'<span style="{style_str}">{remaining_text}</span>')
                                else:
                                    parts.append(remaining_text)
                            break
                        
                        if current_pos < start_pos:
                            text_before = line[current_pos:start_pos]
                            if text_before:
                                styles = []
                                if current_color:
                                    styles.append(f'color: {current_color}')
                                if current_background:
                                    styles.append(f'background-color: {current_background}')
                                if current_stroke:
                                    stroke_color = current_stroke_color if current_stroke_color else invert_color(current_color)
                                    styles.append(f'-webkit-text-stroke: {current_stroke}px {stroke_color}')
                                
                                if current_rotation is not None:
                                    parts.append(apply_rotation_to_text(text_before, current_rotation, styles if styles else None))
                                elif styles:
                                    style_str = '; '.join(styles)
                                    parts.append(f'<span style="{style_str}">{text_before}</span>')
                                else:
                                    parts.append(text_before)
                        
                        if control_type == 'degree':
                            end_pos = line.find('°', start_pos + 1)
                            if end_pos == -1:
                                parts.append(line[start_pos:])
                                break
                            
                            color_code = line[start_pos + 1:end_pos]
                            if color_code in color_map:
                                color_value = color_map[color_code]
                            elif len(color_code) == 6 and all(c in '0123456789ABCDEFabcdef' for c in color_code):
                                color_value = f'#{color_code.upper()}'
                            else:
                                parts.append(line[start_pos:end_pos + 1])
                                current_pos = end_pos + 1
                                continue
                            
                            current_background = color_value if color_value != 'inherit' else None
                            current_pos = end_pos + 1
                        else:
                            end_pos = line.find('%', start_pos + 1)
                            if end_pos == -1:
                                parts.append(line[start_pos:])
                                break
                            
                            control_code = line[start_pos + 1:end_pos]
                            
                            # 图片控制符
                            if control_code.startswith('p '):
                                params_str = control_code[2:].strip()
                                img_params = parse_image_params(params_str)
                                if img_params['file']:
                                    img_src = img_params['file']
                                    size_attr = ''
                                    if img_params['size']:
                                        w, h = img_params['size']
                                        if h:
                                            size_attr = f' width="{w}" height="{h}"'
                                        else:
                                            size_attr = f' width="{w}"'
                                    parts.append(f'<img src="{img_src}" alt="" style="display: inline-block; vertical-align: middle;"{size_attr}>')
                                current_pos = end_pos + 1
                                continue
                            
                            # 描边控制符
                            if control_code.startswith('f '):
                                stroke_params_str = control_code[2:].strip()
                                if stroke_params_str == 'NONE' or 'NONE' in stroke_params_str:
                                    current_stroke = None
                                    current_stroke_color = None
                                else:
                                    stroke_params = parse_stroke_params(stroke_params_str)
                                    if stroke_params['width']:
                                        current_stroke = stroke_params['width']
                                        current_stroke_color = stroke_params['color']
                                current_pos = end_pos + 1
                                continue
                            
                            # 旋转控制符
                            if control_code.startswith('r '):
                                rotation_params = control_code[2:].strip()
                                if rotation_params.startswith('a:'):
                                    try:
                                        angle = float(rotation_params[2:])
                                        current_rotation = angle
                                    except ValueError:
                                        pass
                                elif rotation_params == 'NONE' or 'NONE' in rotation_params:
                                    current_rotation = None
                                current_pos = end_pos + 1
                                continue
                            
                            # 颜色控制符
                            if control_code in color_map:
                                # NONE 特殊处理：重置所有样式
                                if control_code == 'NONE':
                                    current_color = None
                                    current_stroke = None
                                    current_stroke_color = None
                                    current_rotation = None
                                else:
                                    color_value = color_map[control_code]
                                    current_color = color_value if color_value != 'inherit' else None
                                current_pos = end_pos + 1
                                continue
                            elif len(control_code) == 6 and all(c in '0123456789ABCDEFabcdef' for c in control_code):
                                color_value = f'#{control_code.upper()}'
                                current_color = color_value
                                current_pos = end_pos + 1
                                continue
                            else:
                                parts.append(line[start_pos:end_pos + 1])
                                current_pos = end_pos + 1
                                continue
                    
                    processed_lines.append(''.join(parts))
                
                return '\n'.join(processed_lines)
            
            # 先处理颜色控制符
            processed_content = process_color_controls(md_content)
            
            # 转换Markdown为HTML，添加代码高亮、数学公式和文本格式支持
            extensions = [
                FencedCodeExtension(),
                CodeHiliteExtension(
                    css_class='highlight',
                    linenums=False,
                    guess_lang=True
                ),
                'mdx_math',  # 数学公式支持
                'markdown.extensions.attr_list',  # 属性列表支持
                'markdown.extensions.tables',     # 表格支持
                'markdown.extensions.footnotes',  # 脚注支持
                'markdown.extensions.toc',        # 目录支持
                'markdown.extensions.smarty',     # 智能标点符号
                'markdown.extensions.admonition', # 警告框支持
                'markdown.extensions.nl2br',      # 换行转<br>
                'markdown.extensions.sane_lists', # 智能列表
                'markdown.extensions.extra'       # 额外功能（包含删除线等）
            ]
            
            extension_configs = {
                'mdx_math': {
                    'enable_dollar_delimiter': True,
                    'add_preview': True
                }
            }
            
            content = markdown.markdown(processed_content, extensions=extensions, extension_configs=extension_configs)
            
            # 后处理：处理特殊附件链接
            def process_download_links(html_content):
                import re
                
                # 匹配附件链接模式：[dltag:文件名](下载地址)
                pattern = r'<p>\s*<a href="([^"]+)">dltag:([^<]+)</a>\s*</p>'
                
                def replace_download_link(match):
                    download_url = match.group(1)
                    filename = match.group(2)
                    
                    # 转义 URL 和文件名
                    escaped_url = html.escape(download_url)
                    escaped_filename = html.escape(filename)
                    
                    # 生成附件容器HTML
                    return f'''
<div class="download-attachment">
    <div class="attachment-info">
        <span class="filename">{escaped_filename}</span>
        <div class="attachment-actions">
            <button class="info-button" data-url="{escaped_url}">查看信息</button>
            <button class="download-button" onclick="window.open('{escaped_url}', '_blank')" title="下载附件">下载</button>
        </div>
    </div>
    <div class="attachment-details" hidden></div>
</div>
                    '''
                
                # 替换附件链接
                processed_html = re.sub(pattern, replace_download_link, html_content)
                return processed_html
            
            # 应用附件链接处理
            content = process_download_links(content)
            
        except Exception as e:
            print(f"读取文章内容失败: {e}")
            content = '<p>读取文章内容失败</p>'
    else:
        content = '<p>文章内容不存在</p>'
    
    return {
        'title': config.get('title', '无标题'),
        'small_title': config.get('small_title', '无简介'),
        'content': content,
        'update_date': update_date,
        'ai': config.get('ai', '')
    }

@app.route('/api/articles/icon/<category>/<article_id>')
@app.route('/read/<category>/<article_id>/icon')  # 旧接口兼容
def get_article_icon(category, article_id):
    """获取文章封面图片"""
    article_path = os.path.join(BLOG_DIR, category, article_id)
    icon_path = os.path.join(article_path, 'icon.png')
    
    if os.path.exists(icon_path):
        return send_from_directory(article_path, 'icon.png')
    else:
        return send_from_directory('css/all', 'favicon.ico')

# 静态文件路由
@app.route('/css/<path:filename>')
def css_files(filename):
    response = send_from_directory('css', filename)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/css/all/<path:filename>')
def css_all_files(filename):
    response = send_from_directory('css/all', filename)
    if filename == 'bg.png':
        response.headers['Cache-Control'] = 'public, max-age=31536000'
    else:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@app.route('/js/read/comment.js')
def comment_js_file():
    """评论JS文件访问控制"""
    if CLOSE_COMMENT:
        abort(404)
    
    response = send_from_directory('js/read', 'comment.js')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Content-Type'] = 'application/javascript'
    return response

@app.route('/js/<path:filename>')
def js_files(filename):
    response = send_from_directory('js', filename)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/debug/ip')
def debug_ip():
    """调试接口：显示客户端IP信息"""
    real_ip = get_real_client_ip()
    remote_addr = request.remote_addr
    
    return {
        'real_client_ip': real_ip,
        'remote_addr': remote_addr,
        'x_forwarded_for': request.headers.get('X-Forwarded-For'),
        'x_real_ip': request.headers.get('X-Real-IP'),
        'headers': dict(request.headers)
    }

@app.route('/res/<path:filename>')
def resources_files(filename):
    """获取resources目录下的文件"""
    resources_path = os.path.join(os.path.dirname(__file__), 'resources')
    
    # 检查文件是否存在
    file_path = os.path.join(resources_path, filename)
    if not os.path.exists(file_path):
        return {'error': '文件不存在'}, 404
    
    # 检查是否为安全路径（防止路径遍历攻击）
    if '..' in filename or filename.startswith('/'):
        return {'error': '无效的文件路径'}, 400
    
    return send_from_directory(resources_path, filename)

@app.route('/res')
def resources_list():
    """列出resources目录下的所有文件"""
    resources_path = os.path.join(os.path.dirname(__file__), 'resources')
    
    if not os.path.exists(resources_path):
        return {'files': [], 'message': 'resources目录不存在'}
    
    files = []
    try:
        for item in os.listdir(resources_path):
            item_path = os.path.join(resources_path, item)
            if os.path.isfile(item_path):
                files.append({
                    'name': item,
                    'size': os.path.getsize(item_path),
                    'url': f'/res/{item}'
                })
    except Exception as e:
        return {'error': f'读取目录失败: {str(e)}'}, 500
    
    return {'files': files}

@app.route('/api/attachment/info')
def get_attachment_info():
    """获取附件文件信息"""
    url = request.args.get('url', '')
    
    # 解析 URL
    parsed = urllib.parse.urlparse(url)
    
    # 校验协议（必须是 http 或 https，或者相对路径）
    if parsed.scheme and parsed.scheme not in ('http', 'https'):
        return {'error': '非本地资源无法查看'}, 400
    
    # 校验 origin（如果是完整 URL，检查是否为本地）
    if parsed.netloc:
        # 检查是否为当前服务的 origin
        host = request.host
        if parsed.netloc != host:
            return {'error': '非本地资源无法查看'}, 400
    
    # 校验 pathname 前缀（必须以 /res/ 开头）
    pathname = parsed.path
    if not pathname.startswith('/res/'):
        return {'error': '非本地资源无法查看'}, 400
    
    # 安全校验：pathname 不能包含 ..
    if '..' in pathname:
        return {'error': '无效的文件路径'}, 400
    
    # 获取文件名（去除 /res/ 前缀）
    filename = pathname[5:]  # 去除 '/res/'
    
    # 安全校验：文件名不能以 / 开头（防止路径遍历）
    if filename.startswith('/'):
        return {'error': '无效的文件路径'}, 400
    
    # 构建文件路径
    resources_path = os.path.join(os.path.dirname(__file__), 'resources')
    file_path = os.path.join(resources_path, filename)
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        return {'error': '文件不存在'}, 404
    
    # 获取文件信息
    stat_info = os.stat(file_path)
    
    return {
        'created_at': datetime.datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
        'modified_at': datetime.datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
        'size': stat_info.st_size
    }

@app.route('/api/attachment/md5')
def get_attachment_md5():
    """获取附件 MD5 值"""
    # 获取并解析 URL
    url = request.args.get('url', '')
    
    # 安全校验（复用 /api/attachment/info 的逻辑）
    parsed = urllib.parse.urlparse(url)
    
    # 校验协议（必须是 http 或 https，或者相对路径）
    if parsed.scheme and parsed.scheme not in ('http', 'https'):
        return jsonify({'error': '非本地资源无法查看'}), 400
    
    # 校验 origin（如果是完整 URL，检查是否为本地）
    if parsed.netloc:
        host = request.host
        if parsed.netloc != host:
            return jsonify({'error': '非本地资源无法查看'}), 400
    
    # 校验 pathname 前缀（必须以 /res/ 开头）
    pathname = parsed.path
    if not pathname.startswith('/res/'):
        return jsonify({'error': '非本地资源无法查看'}), 400
    
    # 安全校验：pathname 不能包含 ..
    if '..' in pathname:
        return jsonify({'error': '无效的文件路径'}), 400
    
    # 获取文件名（去除 /res/ 前缀）
    filename = pathname[5:]  # 去除 '/res/'
    
    # 安全校验：文件名不能以 / 开头（防止路径遍历）
    if filename.startswith('/'):
        return jsonify({'error': '无效的文件路径'}), 400
    
    # 构建文件路径
    resources_path = os.path.join(os.path.dirname(__file__), 'resources')
    file_path = os.path.join(resources_path, filename)
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        return jsonify({'error': '文件不存在'}), 404
    
    # 使用文件绝对路径作为缓存 key
    cache_key = os.path.abspath(file_path)
    
    # 检查缓存
    with _md5_lock:
        if cache_key in _md5_cache:
            return jsonify(_md5_cache[cache_key])
        if cache_key in _md5_calculating:
            return jsonify({'status': 'calculating'})
    
    # 启动后台线程
    with _md5_lock:
        _md5_calculating.add(cache_key)
        _md5_cache[cache_key] = {"status": "calculating"}
    
    thread = threading.Thread(target=_calculate_md5_thread, args=(file_path, cache_key))
    thread.daemon = True
    thread.start()
    
    return jsonify({'status': 'calculating'})

@app.route('/api/rss.xml')
def rss_feed():
    """RSS订阅源"""
    settings = get_blog_settings()
    with rss_cache_lock:
        articles = rss_articles_cache.copy()
    
    blog_url = request.host_url.rstrip('/')
    last_build_date = datetime.datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0800')
    
    return Response(
        render_template('rss.xml', 
            blogname=settings['blogname'],
            blog_url=blog_url,
            last_build_date=last_build_date,
            articles=articles
        ),
        mimetype='application/rss+xml'
    )

@app.route('/editor')
def editor():
    """Markdown编辑器页面"""
    settings = get_blog_settings()
    return render_template('editor.html', blogname=settings['blogname'])

@app.route('/api/preview', methods=['POST'])
def preview_markdown():
    """Markdown预览API"""
    try:
        data = request.get_json()
        if not data or 'content' not in data:
            return {'error': '缺少内容参数'}, 400
        
        markdown_content = data['content']
        
        # 使用统一的Markdown处理函数
        html_content = process_markdown_content(markdown_content)
        
        return {'html': html_content}
        
    except Exception as e:
        return {'error': f'处理Markdown失败: {str(e)}'}, 500

# 数据库初始化
def init_db():
    """初始化SQLite数据库"""
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'comment.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 创建评论表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            content TEXT NOT NULL,
            avatar_url TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 添加 avatar_url 列（如果不存在）
    try:
        cursor.execute('ALTER TABLE comments ADD COLUMN avatar_url TEXT')
    except sqlite3.OperationalError:
        pass
    
    # 创建用户会话表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            access_token TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

def mask_email(email):
    """邮箱打码函数，保留前两位和@域名部分"""
    if '@' not in email:
        return email
    local_part, domain = email.split('@', 1)
    if len(local_part) <= 2:
        masked_local = local_part
    else:
        masked_local = local_part[:2] + '*' * (len(local_part) - 2)
    return f"{masked_local}@{domain}"

# 提交评论API
@app.route('/api/comment', methods=['POST'])
def api_comment():
    """提交评论接口 - 纯匿名评论"""
    # 检查评论功能是否关闭
    if CLOSE_COMMENT:
        return jsonify({'success': False, 'message': '评论功能已关闭'}), 404
    
    try:
        def is_single_punctuation(text):
            if not text or len(text) != 1:
                return False
            punctuation_chars = (
                '.,!?;:\'\"-()[]{}<>@#$%^&*~`|\\/+=_'
                '。，！？；：""''《》【】（）…—～·、'
                '·※◎■□★☆●○◆◇△▽▼↑←→↘↙♠♣♥♦＃￥％＆＊＋－＝＠＾＿｀｜＼／'
                '〜～￣＿﹏﹋﹌﹍﹎﹏'
                ' \t\r\n'
            )
            return text in punctuation_chars

        if request.is_json:
            data = request.get_json()
            article_id = data.get('article_id')
            content = data.get('content')
            email = data.get('email')
            avatar_url = data.get('avatar_url')
        else:
            article_id = request.form.get('article_id')
            content = request.form.get('content')
            email = request.form.get('email')
            avatar_url = request.form.get('avatar_url')
        
        if not all([article_id, content, email]):
            return jsonify({'success': False, 'message': '文章ID、评论内容和邮箱不能为空'}), 400
        
        if is_single_punctuation(content.strip()):
            return jsonify({'success': False, 'message': '不可发送单个标点符号'}), 400
        
        content = content.replace('\r\n', '').replace('\n', '').replace('\r', '')
        
        if len(content) < 1:
            return jsonify({'success': False, 'message': '评论内容不能为空'}), 400
        
        if len(content) > 1000:
            return jsonify({'success': False, 'message': '评论内容过长（最多1000个字符）'}), 400
        
        anonymous_user_id = f"anonymous#{str(uuid.uuid4())}"
        masked_username = mask_email(email)
        
        db_path = os.path.join(os.path.dirname(__file__), 'instance', 'comment.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO comments (article_id, user_id, username, content, avatar_url)
            VALUES (?, ?, ?, ?, ?)
        ''', (article_id, anonymous_user_id, masked_username, content, avatar_url))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': '评论发布成功',
            'is_anonymous': True,
            'comment_id': cursor.lastrowid
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'评论提交失败: {str(e)}'}), 500

# 获取评论API
@app.route('/api/comments/<path:article_id>', methods=['GET'])
def api_get_comments(article_id):
    """获取文章评论"""
    # 检查评论功能是否关闭
    if CLOSE_COMMENT:
        return jsonify({'success': False, 'message': '评论功能已关闭'}), 404
    
    try:
        db_path = os.path.join(os.path.dirname(__file__), 'instance', 'comment.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, user_id, username, content, avatar_url, created_at
            FROM comments
            WHERE article_id = ?
            ORDER BY created_at DESC
        ''', (article_id,))
        
        comments = []
        for row in cursor.fetchall():
            created_at = row[5]
            
            if isinstance(created_at, str) and ' ' in created_at:
                created_at = created_at.replace(' ', 'T') + 'Z'
            
            avatar_url = row[4] if row[4] else '/css/all/default-avatar.svg'
            
            comments.append({
                'id': row[0],
                'user_id': row[1],
                'username': row[2],
                'content': row[3],
                'created_at': created_at,
                'avatar_url': avatar_url
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'comments': comments
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'获取评论失败: {str(e)}'}), 500

# 用户协议与隐私政策页面
@app.route('/u')
def user_agreement():
    """用户协议与隐私政策页面"""
    return render_template('u.html')

# 修改文章阅读页面，添加评论数据
@app.route('/read/<category>/<article_id>')
def read_article(category, article_id):
    """文章阅读页面"""
    # 获取评论数据（不包含头像，头像通过前端异步加载）
    comments = []
    try:
        db_path = os.path.join(os.path.dirname(__file__), 'instance', 'comment.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT c.id, c.user_id, c.username, c.content, c.created_at
            FROM comments c
            WHERE c.article_id = ?
            ORDER BY c.created_at DESC
        ''', (f"{category}/{article_id}",))
        
        for row in cursor.fetchall():
            # 格式化时间戳，确保前端能正确解析
            created_at = row[4]
            
            # 如果是SQLite的datetime格式，转换为ISO格式
            if isinstance(created_at, str) and ' ' in created_at:
                # 将 "YYYY-MM-DD HH:MM:SS" 转换为 "YYYY-MM-DDTHH:MM:SSZ"
                created_at = created_at.replace(' ', 'T') + 'Z'
            
            # 不在此处获取头像，避免阻塞页面加载
            comments.append({
                'id': row[0],
                'user_id': row[1],
                'username': row[2],
                'content': row[3],
                'created_at': created_at,
                'avatar_url': '/css/all/default-avatar.svg'  # 使用默认头像
            })
        
        conn.close()
    except Exception as e:
        print(f"获取评论失败: {e}")
    
    settings = get_blog_settings()
    return render_template('read.html', 
                          article_id=f"{category}/{article_id}", 
                          comments=comments, 
                          close_comment=CLOSE_COMMENT,
                          blogname=settings['blogname'],
                          author_name=settings.get('author_name', '请在blogsettings.json中设置作者名称'))

@app.route('/browsertest')
def browsertest():
    """浏览器测试页面"""
    # 获取客户端信息
    client_ip = get_real_client_ip()
    user_agent = request.headers.get('User-Agent', '未知')
    request_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    return render_template('browsertest.html',
        client_ip=client_ip,
        user_agent=user_agent,
        request_time=request_time)

# 初始化数据库
init_db()

if __name__ == '__main__':
    app.run(debug=True, port=26178)