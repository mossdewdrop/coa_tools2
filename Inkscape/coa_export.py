#!/usr/bin/env python3
# coding=utf-8

import os
import re
import json
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
        # 1. Try environment variable first
        bin_path = os.environ.get("INKSCAPE_COMMAND")
        if bin_path and os.path.exists(bin_path):
            return bin_path
            
        # 2. Check system PATH
        bin_path = shutil.which("inkscape")
        if bin_path:
            return bin_path
            
        # 3. Common default installation paths
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
        Use Inkscape CLI --query-all to batch query visual bounding boxes of elements.
        Visual bounding boxes include stroke and other rendering effects,
        matching the --export-id export crop area.

        Returns dict {node_id: {'x': x, 'y': y, 'width': w, 'height': h}}
        Coordinates and dimensions are in SVG user units (px = user unit/page coordinate).
        """
        if not node_ids:
            return None
        inkscape_bin = self.find_inkscape_bin()
        # On Windows, prefer inkscape.com (console version) because inkscape.exe
        # may fail to complete queries in a headless environment.
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
            # Format: "id,x,y,w,h"
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
        Check whether a node is visible.

        When Inkscape hides an element via the "eye icon" in the Layers panel,
        it writes display:none in the style attribute. This also handles the
        standard SVG visibility and display attributes.
        """
        if node is None:
            return False

        # 1. Check display and visibility in the style attribute
        style = node.get('style', '')
        if style:
            if re.search(r'display\s*:\s*none', style, re.IGNORECASE):
                return False
            if re.search(r'visibility\s*:\s*(hidden|collapse)', style, re.IGNORECASE):
                return False

        # 2. Check standalone display attribute
        display = node.get('display', '')
        if display and display.lower() == 'none':
            return False

        # 3. Check standalone visibility attribute
        visibility = node.get('visibility', '')
        if visibility and visibility.lower() in ('hidden', 'collapse'):
            return False

        return True

    def get_safe_bbox(self, node):
        """
        Get the geometric bounding box of a node in the SVG root coordinate system
        (user coordinate system). Used to filter valid export nodes, without stroke expansion.
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
        # 1. Intelligently extract selected elements or the active layer
        selected_elements = []
        if self.svg.selection:
            # Prefer rendering order from canvas selection
            if hasattr(self.svg.selection, 'rendering_order'):
                selected_elements = list(self.svg.selection.rendering_order())
            elif hasattr(self.svg.selection, 'paint_order'):
                selected_elements = list(self.svg.selection.paint_order())
            else:
                selected_elements = list(self.svg.selection.values())
        else:
            # If nothing is selected on the canvas, get the currently active layer
            # from the Layers panel.
            current_layer = None
            if hasattr(self.svg, 'get_current_layer'):
                current_layer = self.svg.get_current_layer()
            elif hasattr(self, 'current_layer'):
                current_layer = self.current_layer
                
            if current_layer is not None:
                selected_elements = [current_layer]

        if not selected_elements:
            raise inkex.AbortExtension("Please select the objects to export on the canvas, or select the target layer in the Layers panel.")

        # 2. Use the selected top-level nodes directly, filtering out non-drawing
        #    nodes (e.g., root SvgDocumentElement or metadata defs).
        final_elements = []
        seen = set()
        for node in selected_elements:
            node_id = node.get_id()
            if node_id not in seen:
                # Skip invisible elements (when the "eye icon" in the Layers panel is off)
                if not self.is_node_visible(node):
                    continue
                # Must have a valid bounding box to be a valid exportable graphic
                if self.get_safe_bbox(node) is not None:
                    final_elements.append(node)
                    seen.add(node_id)

        if not final_elements:
            raise inkex.AbortExtension("No valid renderable objects found for export. Please select specific shapes on the canvas, or select a layer in the Layers panel (do not select the root canvas directory).")

        # Reverse order so export goes from top layer to bottom layer
        # (matching Krita's layer-stack order).
        final_elements.reverse()

        # 3. Determine document pixel dimensions and the user-unit-to-pixel scale
        # inkex viewbox_width/bbox returns SVG user units (usually mm),
        # but Krita/Blender expect pixel coordinates. Use the pixel dimensions
        # defined in the SVG document width/height attributes
        # (i.e., the width/height pixel values set in Inkscape's Document Properties).
        # self.px_per_uu = document pixel width / viewBox user-unit width
        doc_width_uu = self.svg.viewbox_width or 1000
        doc_height_uu = self.svg.viewbox_height or 1000
        _vp_w = self.svg.viewport_width if hasattr(self.svg, 'viewport_width') else self.svg.width
        _vp_h = self.svg.viewport_height if hasattr(self.svg, 'viewport_height') else self.svg.height
        doc_width_px = _vp_w.to_px() if hasattr(_vp_w, 'to_px') else float(_vp_w)
        doc_height_px = _vp_h.to_px() if hasattr(_vp_h, 'to_px') else float(_vp_h)
        self.px_per_uu = doc_width_px / doc_width_uu if doc_width_uu else 1.0

        viewbox_width = doc_width_px
        viewbox_height = doc_height_px

        # viewBox/page origin offset (converted to pixels)
        origin_x = (getattr(self.svg, 'viewbox_x', 0) or 0) * self.px_per_uu
        origin_y = (getattr(self.svg, 'viewbox_y', 0) or 0) * self.px_per_uu

        # Get multi-page support list (Inkscape 1.2+)
        pages = []
        if hasattr(self.svg, 'get_pages'):
            pages = self.svg.get_pages()

        current_page_idx = 0
        if pages:
            # Find the page with the greatest overlap with the combined bounding box
            # of the selected elements.
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

            # Use the current page dimensions (converted to pixels,
            # matching Krita's doc.width/height semantics).
            if hasattr(self.svg, 'get_page_bbox'):
                try:
                    page_bbox = self.svg.get_page_bbox(current_page_idx)
                    if page_bbox is not None:
                        viewbox_width = page_bbox.width * self.px_per_uu
                        viewbox_height = page_bbox.height * self.px_per_uu
                        # Page top-left offset in the SVG root coordinate system (converted to pixels)
                        origin_x = page_bbox.left * self.px_per_uu
                        origin_y = page_bbox.top * self.px_per_uu
                except IndexError:
                    pass

        # 4. Determine the export path intelligently
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
                raise inkex.AbortExtension(f"Could not create export path: {e}")

        sprites_dir = os.path.join(export_path, "sprites")
        if not os.path.exists(sprites_dir):
            try:
                os.makedirs(sprites_dir)
            except Exception as e:
                raise inkex.AbortExtension(f"Could not create sprites folder: {e}")

        # 5. Initialize JSON metadata structure
        json_data = OrderedDict()
        json_data["name"] = self.options.export_name
        json_data["nodes"] = []

        # 6. Write a temporary SVG file and export each node
        temp_svg_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as temp_svg:
                self.document.write(temp_svg)
                temp_svg_path = temp_svg.name

            # Batch query Inkscape visual bounding boxes (identical to --export-id crop area)
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

                # Use Inkscape visual bounding box (identical to --export-id crop area).
                # --query-all returns (x, y) as the top-left corner of the visual
                # bounding box in the document coordinate system, in SVG user units
                # (equivalent to page px).
                #
                # For a viewBox starting at (0,0) with no pages, origin_x/origin_y
                # are 0, so values are used directly. For multi-page scenarios,
                # the page offset must be subtracted.
                pos_x = 0.0
                pos_y = 0.0
                if visual_bboxes and node_id in visual_bboxes:
                    vb = visual_bboxes[node_id]
                    # Inkscape uses the SVG viewBox origin as the top-left corner.
                    # However, in Krita/COA Tools, position uses the document/page
                    # top-left as the origin. When a page offset exists (origin_x/y != 0),
                    # correction is needed.
                    pos_x = vb['x'] - origin_x
                    pos_y = vb['y'] - origin_y
                else:
                    # Fallback to inkex geometric bounding box (no stroke compensation)
                    bbox = self.get_safe_bbox(node)
                    if bbox is not None:
                        pos_x = bbox.left * self.px_per_uu - origin_x
                        pos_y = bbox.top * self.px_per_uu - origin_y

                # Offset is based on viewBox size (matching Krita's offset
                # based on doc.width/height).
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
                # Compute the corresponding Z-index (topmost = largest, bottom = 0,
                # identical to Krita).
                new_node["z"] = len(final_elements) - i - 1
                new_node["tiles_x"] = 1
                new_node["tiles_y"] = 1
                new_node["frame_index"] = 0
                new_node["children"] = []
                new_node["path"] = filename

                json_data["nodes"].append(new_node)

                self.export_node(temp_svg_path, filepath, node_id)

                # Fill transparent regions of the exported PNG with color
                self.alpha_fill_png(filepath)

            # 7. Write JSON metadata file
            json_path = os.path.join(export_path, f"{self.options.export_name}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent="\t")

        except Exception as e:
            raise inkex.AbortExtension(f"Error during export: {e}")
        finally:
            if temp_svg_path and os.path.exists(temp_svg_path):
                try:
                    os.remove(temp_svg_path)
                except Exception:
                    pass

    def alpha_fill_png(self, filepath, threshold=10):
        """
        Fill transparent regions of an exported PNG with nearby opaque colors.

        Uses a BFS flood-fill algorithm to fill transparent pixels' RGB channels
        with the color of the nearest non-transparent pixel, while preserving the
        original alpha channel values.

        Reference implementation: img-alpha-fill/index.html
        """
        try:
            from PIL import Image
        except ImportError:
            inkex.errormsg(
                "Warning: Pillow library not found, cannot fill transparent regions.\n"
                "Run: pip install Pillow\n"
                "Transparent region color fill will be skipped."
            )
            return

        try:
            img = Image.open(filepath).convert('RGBA')
        except Exception:
            return

        width, height = img.size
        pixels = img.load()

        # Create result image
        result = Image.new('RGBA', (width, height))
        result_pixels = result.load()

        # Copy original pixels
        for y in range(height):
            for x in range(width):
                result_pixels[x, y] = pixels[x, y]

        # BFS initialization: visited=1 means opaque/processed, visited=0 means transparent/unprocessed
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
            # No processing needed
            result.save(filepath, 'PNG')
            img.close()
            result.close()
            return

        # 4-direction BFS flood fill
        offsets = [(0, -1), (0, 1), (-1, 0), (1, 0)]

        while current_queue:
            for x, y in current_queue:
                r, g, b, _ = result_pixels[x, y]

                for dx, dy in offsets:
                    nx, ny = x + dx, y + dy

                    if 0 <= nx < width and 0 <= ny < height and visited[ny][nx] == 0:
                        result_pixels[nx, ny] = (r, g, b, 255)  # Temporarily set alpha to 255 to mark processed
                        visited[ny][nx] = 1
                        next_queue.append((nx, ny))

            current_queue = next_queue
            next_queue = []

        # Restore original alpha channel
        for y in range(height):
            for x in range(width):
                pr, pg, pb, _ = result_pixels[x, y]
                _, _, _, oa = pixels[x, y]
                result_pixels[x, y] = (pr, pg, pb, oa)

        result.save(filepath, 'PNG')
        img.close()
        result.close()

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
                    err_msg = f"\nDetailed error: {ex.stderr.decode('utf-8', errors='ignore')}"
                inkex.errormsg(f"Failed to export element '{node_id}' to '{filepath}'. {ex}{err_msg}")

if __name__ == "__main__":
    BatchExportMetadata().run()
