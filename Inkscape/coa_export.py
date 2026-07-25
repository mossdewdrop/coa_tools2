#!/usr/bin/env python3
# coding=utf-8

import os
import re
import json
import uuid
import filecmp
import tempfile
import subprocess
import shutil
from collections import OrderedDict

import inkex
from inkex.command import inkscape, ProgramRunError

class BatchExportMetadata(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--export_path", type=str, default="~/")
        pars.add_argument("--export_name", type=str, default="Actor_Goblin")
        pars.add_argument("--suffix", type=str, default="")
        pars.add_argument("--dpi", type=int, default=96)
        pars.add_argument("--overwrite", type=inkex.Boolean, default=True)

    def find_inkscape_bin(self):
        # 1. 优先尝试环境变量
        bin_path = os.environ.get("INKSCAPE_COMMAND")
        if bin_path and os.path.exists(bin_path):
            return bin_path
            
        # 2. 检查系统 PATH
        bin_path = shutil.which("inkscape")
        if bin_path:
            return bin_path
            
        # 3. 常见系统默认安装路径
        if os.name == 'nt':  # Windows
            paths = [
                r"C:\Program Files\Inkscape\bin\inkscape.exe",
                r"C:\Program Files\Inkscape\inkscape.exe",
                r"C:\Program Files (x86)\Inkscape\bin\inkscape.exe",
                r"C:\Program Files (x86)\Inkscape\inkscape.exe",
            ]
            for p in paths:
                if os.path.exists(p):
                    return p
        else:  # macOS / Linux
            paths = [
                "/Applications/Inkscape.app/Contents/Resources/bin/inkscape",
                "/Applications/Inkscape.app/Contents/MacOS/inkscape",
                "/usr/bin/inkscape",
                "/usr/local/bin/inkscape",
            ]
            for p in paths:
                if os.path.exists(p):
                    return p
                    
        return "inkscape"

    def query_visual_bboxes(self, svg_path, node_ids):
        """
        使用 Inkscape CLI --query-all 批量查询元素的视觉边界框。
        视觉边界框包含描边等渲染效果，与 --export-id 的导出裁剪区域一致。

        返回 dict {node_id: {'x': x, 'y': y, 'width': w, 'height': h}}
        坐标和尺寸单位为 SVG 用户单位（px = user unit/page coordinate）。
        """
        if not node_ids:
            return None
        inkscape_bin = self.find_inkscape_bin()
        # Windows 上优先用 inkscape.com（控制台版本），inkscape.exe 可能在
        # 无 GUI 环境下无法完成查询
        if os.name == 'nt':
            com_path = os.path.join(os.path.dirname(inkscape_bin), 'inkscape.com')
            if os.path.exists(com_path):
                inkscape_bin = com_path

        cmd = [inkscape_bin, svg_path, "--query-all"]

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True, startupinfo=startupinfo
            )
        except Exception:
            return None

        lookup = set(node_ids)
        results = {}
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            # 格式: "id,x,y,w,h"
            parts = line.split(',')
            if len(parts) < 5:
                continue
            qid = parts[0].strip()
            if qid in lookup:
                results[qid] = {
                    'x': float(parts[1]),
                    'y': float(parts[2]),
                    'width': float(parts[3]),
                    'height': float(parts[4]),
                }
                if len(results) == len(node_ids):
                    break

        return results if results and len(results) == len(node_ids) else None

    def is_node_visible(self, node):
        """
        检查节点是否为可见状态。

        Inkscape 在图层面板点击"眼睛图标"隐藏元素时，
        会在 style 中写入 display:none。同时兼容 SVG
        标准属性 visibility 和 display。
        """
        if node is None:
            return False

        # 1. 检查 style 属性中的 display 和 visibility
        style = node.get('style', '')
        if style:
            if re.search(r'display\s*:\s*none', style, re.IGNORECASE):
                return False
            if re.search(r'visibility\s*:\s*(hidden|collapse)', style, re.IGNORECASE):
                return False

        # 2. 检查独立 display 属性
        display = node.get('display', '')
        if display and display.lower() == 'none':
            return False

        # 3. 检查独立 visibility 属性
        visibility = node.get('visibility', '')
        if visibility and visibility.lower() in ('hidden', 'collapse'):
            return False

        return True

    def get_safe_bbox(self, node):
        """
        获取节点在 SVG 根坐标系（用户坐标系）中的几何边界框。
        用于过滤有效导出节点，不使用描边扩展。
        """
        if node is None or not hasattr(node, 'bounding_box'):
            return None
        bbox_attr = node.bounding_box
        if callable(bbox_attr):
            try:
                _parent = node.getparent()
                if _parent is not None and hasattr(_parent, 'composed_transform'):
                    return bbox_attr(_parent.composed_transform())
            except Exception:
                pass
            return bbox_attr()
        return bbox_attr

    def effect(self):
        # 1. 智能提取选中的元素或活动图层
        selected_elements = []
        if self.svg.selection:
            # 优先从画布选中项中按渲染顺序提取元素
            if hasattr(self.svg.selection, 'rendering_order'):
                selected_elements = list(self.svg.selection.rendering_order())
            elif hasattr(self.svg.selection, 'paint_order'):
                selected_elements = list(self.svg.selection.paint_order())
            else:
                selected_elements = list(self.svg.selection.values())
        else:
            # 若画布无选中，则获取用户在图层面板中选中的当前活动图层
            current_layer = None
            if hasattr(self.svg, 'get_current_layer'):
                current_layer = self.svg.get_current_layer()
            elif hasattr(self, 'current_layer'):
                current_layer = self.current_layer
                
            if current_layer is not None:
                selected_elements = [current_layer]

        if not selected_elements:
            raise inkex.AbortExtension("请先在画布中选择要导出的对象，或者在图层面板中选中目标图层。")

        # 2. 直接使用选中的顶级节点，过滤掉非绘图节点（如根画布 SvgDocumentElement 或元数据 defs）
        final_elements = []
        seen = set()
        for node in selected_elements:
            node_id = node.get_id()
            if node_id not in seen:
                # 跳过不可见的元素（图层面板的"眼睛图标"关闭时）
                if not self.is_node_visible(node):
                    continue
                # 必须拥有能够成功读取的有效 Bounding Box 才是有效导出图形
                if self.get_safe_bbox(node) is not None:
                    final_elements.append(node)
                    seen.add(node_id)

        if not final_elements:
            raise inkex.AbortExtension("未找到任何支持导出的有效渲染对象。请先在画布中选中具体的图形，或在图层面板中选中一个图层（不要选中根画布目录）。")

        # 翻转排序，使导出顺序从顶层到底层（与 Krita 的 layer-stack 顺序一致）
        final_elements.reverse()

        # 3. 确定文档像素尺寸及用户单位到像素的缩放比
        # inkex 的 viewbox_width/bbox 返回 SVG 用户单位（通常是 mm），
        # 而 Krita/Blender 期望像素坐标系。使用 SVG 文档 width/height 属性
        # 定义的像素尺寸作为依据（即 Inkscape 文档属性中设置的"宽度/高度"像素值）。
        # self.px_per_uu = 文档像素宽度 / viewBox 用户单位宽度
        doc_width_uu = self.svg.viewbox_width or 1000
        doc_height_uu = self.svg.viewbox_height or 1000
        _vp_w = self.svg.viewport_width if hasattr(self.svg, 'viewport_width') else self.svg.width
        _vp_h = self.svg.viewport_height if hasattr(self.svg, 'viewport_height') else self.svg.height
        doc_width_px = _vp_w.to_px() if hasattr(_vp_w, 'to_px') else float(_vp_w)
        doc_height_px = _vp_h.to_px() if hasattr(_vp_h, 'to_px') else float(_vp_h)
        self.px_per_uu = doc_width_px / doc_width_uu if doc_width_uu else 1.0

        viewbox_width = doc_width_px
        viewbox_height = doc_height_px

        # viewBox/页面的原点偏移（转换为像素）
        origin_x = (getattr(self.svg, 'viewbox_x', 0) or 0) * self.px_per_uu
        origin_y = (getattr(self.svg, 'viewbox_y', 0) or 0) * self.px_per_uu

        # 获取多页面支持列表 (Inkscape 1.2+)
        pages = []
        if hasattr(self.svg, 'get_pages'):
            pages = self.svg.get_pages()

        current_page_idx = 0
        if pages:
            # 通过计算选中元素的联合边界，寻找与之重合度最大的页面作为当前活动页面
            bboxes = [self.get_safe_bbox(el) for el in final_elements]
            bboxes = [b for b in bboxes if b is not None]
            if bboxes:
                elements_bbox = bboxes[0]
                for b in bboxes[1:]:
                    elements_bbox += b

                max_overlap_area = -1
                for idx, page in enumerate(pages):
                    page_bbox_view = self.get_safe_bbox(page)
                    if page_bbox_view is not None:
                        overlap = page_bbox_view & elements_bbox
                        if overlap is not None:
                            overlap_area = overlap.width * overlap.height
                            if overlap_area > max_overlap_area:
                                max_overlap_area = overlap_area
                                current_page_idx = idx

            # 使用当前页面的尺寸（转换为像素，匹配 Krita 中 doc.width/height 的语义）
            if hasattr(self.svg, 'get_page_bbox'):
                try:
                    page_bbox = self.svg.get_page_bbox(current_page_idx)
                    if page_bbox is not None:
                        viewbox_width = page_bbox.width * self.px_per_uu
                        viewbox_height = page_bbox.height * self.px_per_uu
                        # 页面在 SVG 根坐标系中的左上角偏移（转换为像素）
                        origin_x = page_bbox.left * self.px_per_uu
                        origin_y = page_bbox.top * self.px_per_uu
                except IndexError:
                    pass

        # 4. 智能决定保存路径
        raw_path = self.options.export_path
        svg_file_path = self.document_path()
        
        if (raw_path == "~/" or not raw_path) and svg_file_path:
            export_path = os.path.dirname(svg_file_path)
        else:
            export_path = os.path.expanduser(raw_path or "~/")

        if not os.path.exists(export_path):
            try:
                os.makedirs(export_path)
            except Exception as e:
                raise inkex.AbortExtension(f"无法创建导出路径: {e}")

        sprites_dir = os.path.join(export_path, "sprites")
        if not os.path.exists(sprites_dir):
            try:
                os.makedirs(sprites_dir)
            except Exception as e:
                raise inkex.AbortExtension(f"无法创建 sprites 文件夹: {e}")

        # 5. 初始化 JSON 元数据结构
        json_data = OrderedDict()
        json_data["name"] = self.options.export_name
        json_data["nodes"] = []

        # 6. 写入临时 SVG 文件并遍历导出
        temp_svg_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as temp_svg:
                self.document.write(temp_svg)
                temp_svg_path = temp_svg.name

            # 批量查询 Inkscape 视觉边界框（与 --export-id 导出区域完全一致）
            node_ids = [node.get_id() for node in final_elements]
            visual_bboxes = self.query_visual_bboxes(temp_svg_path, node_ids)

            for i, node in enumerate(final_elements):
                node_id = node.get_id()
                
                if hasattr(node, 'label') and node.label:
                    label = node.label
                else:
                    label = node.get("inkscape:label") or node_id

                clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', label)
                clean_name = clean_name.replace(" ", "_").lower()
                
                if self.options.suffix:
                    clean_name = f"{clean_name}{self.options.suffix}"

                ext = "png"
                filename = f"{clean_name}.{ext}"
                filepath = os.path.join(sprites_dir, filename)

                # 处理重名文件：先导出到 hash 临时文件，再与已有文件比对内容
                if os.path.exists(filepath):
                    temp_name = f"_tmp_{uuid.uuid4().hex}.png"
                    temp_path = os.path.join(sprites_dir, temp_name)

                    self.export_node(temp_svg_path, temp_path, node_id)
                    self.alpha_fill_png(temp_path)

                    if self._images_match(temp_path, filepath):
                        # 内容完全相同，复用已有文件，删除临时文件
                        os.remove(temp_path)
                    else:
                        # 内容不同，寻找下一个可用序号
                        counter = 1
                        while True:
                            dedup_name = f"{clean_name}_{counter}.{ext}"
                            dedup_path = os.path.join(sprites_dir, dedup_name)
                            if not os.path.exists(dedup_path):
                                break
                            counter += 1
                        os.rename(temp_path, dedup_path)
                        filename = dedup_name
                        filepath = dedup_path
                else:
                    # 无重名，正常导出
                    self.export_node(temp_svg_path, filepath, node_id)
                    self.alpha_fill_png(filepath)

                # 使用 Inkscape 视觉边界框（与 --export-id 的导出裁剪区域完全一致）
                # --query-all 返回的 x,y 是视觉边界框左上角在文档坐标系中的坐标，
                # 单位为 SVG 用户单位（等同于 page px）。

                # 对于 viewBox 起始于 (0,0) 的无页面情况，origin_x/origin_y 为 0，
                # 直接取值即可。对于多页面场景，需减去页面偏移。
                pos_x = 0.0
                pos_y = 0.0
                if visual_bboxes and node_id in visual_bboxes:
                    vb = visual_bboxes[node_id]
                    # Inkscape 以 SVG viewBox 原点为左上角。
                    # 但在 Krita/COA Tools 中，position 以文档/page 左上角为原点。
                    # 对于有页面偏移（origin_x/y ≠ 0）的情况，需要校正。
                    pos_x = vb['x'] - origin_x
                    pos_y = vb['y'] - origin_y
                else:
                    # 回退到 inkex 几何边界框（无描边补偿）
                    bbox = self.get_safe_bbox(node)
                    if bbox is not None:
                        pos_x = bbox.left * self.px_per_uu - origin_x
                        pos_y = bbox.top * self.px_per_uu - origin_y

                # 偏移量基于 viewBox 尺寸（与 Krita 的 offset 基于 doc.width/height 一致）
                offset_x = int(-viewbox_width / 2)
                offset_y = int(viewbox_height / 2)

                new_node = OrderedDict()
                new_node["name"] = filename
                new_node["type"] = "SPRITE"
                new_node["node_path"] = filename
                new_node["resource_path"] = f"sprites/{filename}"
                new_node["pivot_offset"] = [0, 0]
                new_node["offset"] = [offset_x, offset_y]
                new_node["position"] = [pos_x, pos_y]
                new_node["rotation"] = 0
                new_node["scale"] = [1, 1]
                new_node["opacity"] = [0, 0]
                # 计算对应的 Z-index (顶层最大，底层为 0，与 Krita 完全相同)
                new_node["z"] = len(final_elements) - i - 1
                new_node["tiles_x"] = 1
                new_node["tiles_y"] = 1
                new_node["frame_index"] = 0
                new_node["children"] = []
                new_node["path"] = filename

                json_data["nodes"].append(new_node)

            # 7. 写入 JSON 元数据文件
            json_path = os.path.join(export_path, f"{self.options.export_name}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent="\t")

        except Exception as e:
            raise inkex.AbortExtension(f"导出过程中发生错误: {e}")
        finally:
            if temp_svg_path and os.path.exists(temp_svg_path):
                try:
                    os.remove(temp_svg_path)
                except Exception:
                    pass

    def alpha_fill_png(self, filepath, threshold=10):
        """
        对导出的 PNG 图片执行透明区域颜色填充。
        使用 BFS 洪泛算法，将透明像素的 RGB 填充为距离最近的非透明像素颜色，
        同时保留原始 Alpha 通道值不变。

        参考实现: img-alpha-fill/index.html
        """
        try:
            from PIL import Image
        except ImportError:
            inkex.errormsg(
                "警告: 未找到 Pillow 库，无法执行透明区域颜色填充。\n"
                "请运行: pip install Pillow\n"
                "透明区域颜色填充功能将被跳过。"
            )
            return

        try:
            img = Image.open(filepath).convert('RGBA')
        except Exception:
            return

        width, height = img.size
        pixels = img.load()

        # 创建结果图像
        result = Image.new('RGBA', (width, height))
        result_pixels = result.load()

        # 复制原始像素
        for y in range(height):
            for x in range(width):
                result_pixels[x, y] = pixels[x, y]

        # BFS 初始化: visited=1 表示不透明/已处理, visited=0 表示透明/未处理
        visited = [[0] * width for _ in range(height)]
        current_queue = []
        next_queue = []

        for y in range(height):
            for x in range(width):
                r, g, b, a = pixels[x, y]
                if a >= threshold:
                    visited[y][x] = 1
                    current_queue.append((x, y))

        total_pixels = width * height
        if len(current_queue) == 0 or len(current_queue) == total_pixels:
            # 无需处理
            result.save(filepath, 'PNG')
            img.close()
            result.close()
            return

        # 4 方向 BFS 洪泛
        offsets = [(0, -1), (0, 1), (-1, 0), (1, 0)]

        while current_queue:
            for x, y in current_queue:
                r, g, b, _ = result_pixels[x, y]

                for dx, dy in offsets:
                    nx, ny = x + dx, y + dy

                    if 0 <= nx < width and 0 <= ny < height and visited[ny][nx] == 0:
                        result_pixels[nx, ny] = (r, g, b, 255)  # 临时置 Alpha 为 255 标记已处理
                        visited[ny][nx] = 1
                        next_queue.append((nx, ny))

            current_queue = next_queue
            next_queue = []

        # 恢复原始 Alpha 通道
        for y in range(height):
            for x in range(width):
                pr, pg, pb, _ = result_pixels[x, y]
                _, _, _, oa = pixels[x, y]
                result_pixels[x, y] = (pr, pg, pb, oa)

        result.save(filepath, 'PNG')
        img.close()
        result.close()

    def _images_match(self, path1, path2, hash_size=8, threshold=5):
        """
        通过感知哈希（phash）比较两张 PNG 是否视觉一致，忽略元数据差异。

        使用 ImageHash 库的 phash 算法计算两张图片的感知哈希，
        若汉明距离 <= threshold 则判定为视觉相同。

        hash_size 控制 phash 精度（默认 8 → 64 bit hash）。
        threshold 为汉明距离阈值，两张完全相同的图距离为 0。
        """
        try:
            import imagehash
            from PIL import Image
            hash1 = imagehash.phash(Image.open(path1), hash_size=hash_size)
            hash2 = imagehash.phash(Image.open(path2), hash_size=hash_size)
            return (hash1 - hash2) <= threshold
        except ImportError:
            # ImageHash 不可用 → 回退到像素级比较
            try:
                from PIL import Image
                img1 = Image.open(path1).convert('RGBA')
                img2 = Image.open(path2).convert('RGBA')
                if img1.size != img2.size:
                    return False
                return img1.tobytes() == img2.tobytes()
            except ImportError:
                # PIL 也不可用 → 回退到文件字节比较
                return filecmp.cmp(path1, path2, shallow=False)
        except Exception:
            return False

    def export_node(self, svg_file, filepath, node_id):
        kwargs = {
            'export_filename': filepath,
            'export_id': node_id,
            'export_id_only': True,
            'export_type': 'png',
            'export_dpi': str(self.options.dpi),
        }
        if self.options.overwrite:
            kwargs['export_overwrite'] = True

        try:
            inkscape(svg_file, **kwargs)
        except (ProgramRunError, ImportError, AttributeError, TypeError, Exception):
            inkscape_bin = self.find_inkscape_bin()
            cmd = [
                inkscape_bin,
                svg_file,
                f"--export-filename={filepath}",
                f"--export-id={node_id}",
                "--export-id-only",
                "--export-type=png",
                f"--export-dpi={self.options.dpi}",
            ]
            if self.options.overwrite:
                cmd.append("--export-overwrite")

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            try:
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            except Exception as ex:
                err_msg = ""
                if hasattr(ex, 'stderr') and ex.stderr:
                    err_msg = f"\n详细错误信息: {ex.stderr.decode('utf-8', errors='ignore')}"
                inkex.errormsg(f"导出元素 '{node_id}' 到 '{filepath}' 失败。{ex}{err_msg}")

if __name__ == "__main__":
    BatchExportMetadata().run()