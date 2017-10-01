#!/usr/bin/env python

"""
This is a web service to print labels on Brother QL label printers.
"""

import sys, logging, socket, os, functools, textwrap
from io import BytesIO

from bottle import run, route, get, post, response, request, jinja2_view as view, static_file, redirect
from PIL import Image, ImageDraw, ImageFont

from brother_ql.devicedependent import models, label_type_specs, label_sizes
from brother_ql.devicedependent import ENDLESS_LABEL, DIE_CUT_LABEL, ROUND_DIE_CUT_LABEL
from brother_ql import BrotherQLRaster, create_label
from brother_ql.backends import backend_factory, guess_backend

from font_helpers import get_fonts

logger = logging.getLogger(__name__)

DEBUG = False
MODEL = None
BACKEND_CLASS = None
BACKEND_STRING_DESCR = None
DEFAULT_ORIENTATION = None
DEFAULT_LABEL_SIZE = None
FONTS = None
DEFAULT_FONT = None
DEFAULT_FONTS = [
  {'family': 'Minion Pro',      'style': 'Semibold'},
  {'family': 'Linux Libertine', 'style': 'Regular'},
  {'family': 'DejaVu Serif',    'style': 'Book'},
]

LABEL_SIZES = [ (name, label_type_specs[name]['name']) for name in label_sizes]

@route('/')
def index():
    redirect('/labeldesigner')

@route('/static/<filename:path>')
def serve_static(filename):
    return static_file(filename, root='./static')

@route('/labeldesigner')
@view('labeldesigner.jinja2')
def labeldesigner():
    fonts = sorted(list(FONTS.keys()))
    label_sizes = LABEL_SIZES
    title = 'Label Designer'
    page_headline = 'Brother QL Label Designer'
    return {'title': title, 'page_headline': page_headline, 'message': '', 'fonts': fonts, 'label_sizes': label_sizes, 'default_label_size': DEFAULT_LABEL_SIZE, 'default_orientation': DEFAULT_ORIENTATION}

def get_label_context(request):
    """ might raise LookupError() """

    d = request.params.decode() # UTF-8 decoded form data

    context = {
      'text':          d.get('text', None),
      'font_size': int(d.get('font_size', 100)),
      'font_family':   d.get('font_family'),
      'font_style':    d.get('font_style'),
      'label_size':    d.get('label_size', "62"),
      'kind':          label_type_specs[d.get('label_size', "62")]['kind'],
      'margin':    int(d.get('margin', 10)),
      'threshold': int(d.get('threshold', 70)),
      'align':         d.get('align', 'center'),
      'orientation':   d.get('orientation', 'standard'),
      'margin_top':    float(d.get('margin_top',    24))/100.,
      'margin_bottom': float(d.get('margin_bottom', 45))/100.,
      'margin_left':   float(d.get('margin_left',   35))/100.,
      'margin_right':  float(d.get('margin_right',  35))/100.,
    }
    context['margin_top']    = int(context['font_size']*context['margin_top'])
    context['margin_bottom'] = int(context['font_size']*context['margin_bottom'])
    context['margin_left']   = int(context['font_size']*context['margin_left'])
    context['margin_right']  = int(context['font_size']*context['margin_right'])

    def get_font_path(font_family, font_style):
        try:
            if font_family is None:
                font_family = DEFAULT_FONT['family']
                font_style =  DEFAULT_FONT['style']
            if font_style is None:
                font_style =  'Regular'
            font_path = FONTS[font_family][font_style]
        except KeyError:
            raise LookupError("Couln't find the font & style")
        return font_path

    context['font_path'] = get_font_path(context['font_family'], context['font_style'])

    def get_label_dimensions(label_size):
        try:
            ls = label_type_specs[context['label_size']]
        except KeyError:
            raise LookupError("Unknown label_size")
        return ls['dots_printable']

    width, height = get_label_dimensions(context['label_size'])
    if height > width: width, height = height, width
    if context['orientation'] == 'rotated': height, width = width, height
    context['width'], context['height'] = width, height

    return context

def create_label_im(text, **kwargs):
    label_type = kwargs['kind']
    im_font = ImageFont.truetype(kwargs['font_path'], kwargs['font_size'])
    im = Image.new('L', (20, 20), 'white')
    draw = ImageDraw.Draw(im)
    # workaround for a bug in multiline_textsize()
    # when there are empty lines in the text:
    lines = []
    for line in text.split('\n'):
        if line == '': line = ' '
        lines.append(line)
    text = '\n'.join(lines)
    linesize = im_font.getsize(text)
    textsize = draw.multiline_textsize(text, font=im_font)
    width, height = kwargs['width'], kwargs['height']
    if kwargs['orientation'] == 'standard':
        if label_type in (ENDLESS_LABEL,):
            height = textsize[1] + kwargs['margin_top'] + kwargs['margin_bottom']
    elif kwargs['orientation'] == 'rotated':
        if label_type in (ENDLESS_LABEL,):
            width = textsize[0] + kwargs['margin_left'] + kwargs['margin_right']
    im = Image.new('L', (width, height), 'white')
    draw = ImageDraw.Draw(im)
    if kwargs['orientation'] == 'standard':
        if label_type in (DIE_CUT_LABEL, ROUND_DIE_CUT_LABEL):
            vertical_offset  = (height - textsize[1])//2
            vertical_offset += (kwargs['margin_top'] - kwargs['margin_bottom'])//2
        else:
            vertical_offset = kwargs['margin_top']
        horizontal_offset = max((width - textsize[0])//2, 0)
    elif kwargs['orientation'] == 'rotated':
        vertical_offset  = (height - textsize[1])//2
        vertical_offset += (kwargs['margin_top'] - kwargs['margin_bottom'])//2
        if label_type in (DIE_CUT_LABEL, ROUND_DIE_CUT_LABEL):
            horizontal_offset = max((width - textsize[0])//2, 0)
        else:
            horizontal_offset = kwargs['margin_left']
    offset = horizontal_offset, vertical_offset
    draw.multiline_text(offset, text, (0), font=im_font, align=kwargs['align'])
    return im

@get('/api/preview/text')
@post('/api/preview/text')
def get_preview_image():
    context = get_label_context(request)
    im = create_label_im(**context)
    return_format = request.query.get('return_format', 'png')
    if return_format == 'base64':
        import base64
        response.set_header('Content-type', 'text/plain')
        return base64.b64encode(image_to_png_bytes(im))
    else:
        response.set_header('Content-type', 'image/png')
        return image_to_png_bytes(im)

def image_to_png_bytes(im):
    image_buffer = BytesIO()
    im.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    return image_buffer.read()

@post('/api/print/text')
@get('/api/print/text')
def print_text():
    """
    API to print a label

    returns: JSON

    Ideas for additional URL parameters:
    - alignment
    """

    return_dict = {'success': False}

    try:
        context = get_label_context(request)
    except LookupError as e:
        return_dict['error'] = e.msg
        return return_dict

    if context['text'] is None:
        return_dict['error'] = 'Please provide the text for the label'
        return return_dict

    im = create_label_im(**context)
    if DEBUG: im.save('sample-out.png')

    if context['kind'] == ENDLESS_LABEL:
        rotate = 0 if context['orientation'] == 'standard' else 90
    elif context['kind'] in (ROUND_DIE_CUT_LABEL, DIE_CUT_LABEL):
        rotate = 'auto'

    qlr = BrotherQLRaster(MODEL)
    create_label(qlr, im, context['label_size'], threshold=context['threshold'], cut=True, rotate=rotate)

    if not DEBUG:
        try:
            be = BACKEND_CLASS(BACKEND_STRING_DESCR)
            be.write(qlr.data)
            be.dispose()
            del be
        except Exception as e:
            return_dict['message'] = str(e)
            logger.warning('Exception happened: %s', e)
            return return_dict

    return_dict['success'] = True
    if DEBUG: return_dict['data'] = str(qlr.data)
    return return_dict

def main():
    global DEBUG, FONTS, DEFAULT_FONT, MODEL, BACKEND_CLASS, BACKEND_STRING_DESCR, DEFAULT_ORIENTATION, DEFAULT_LABEL_SIZE
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default=8013)
    parser.add_argument('--loglevel', type=lambda x: getattr(logging, x.upper()), default='WARNING')
    parser.add_argument('--font-folder', help='folder for additional .ttf/.otf fonts')
    parser.add_argument('--default-label-size', default="62", help='Label size inserted in your printer. Defaults to 62.')
    parser.add_argument('--default-orientation', default="standard", choices=('standard', 'rotated'), help='Label orientation, defaults to "standard". To turn your text by 90°, state "rotated".')
    parser.add_argument('--model', default='QL-500', choices=models, help='The model of your printer (default: QL-500)')
    parser.add_argument('printer', help='String descriptor for the printer to use (like tcp://192.168.0.23:9100 or file:///dev/usb/lp0)')
    args = parser.parse_args()

    DEBUG = args.loglevel == logging.DEBUG
    logging.basicConfig(level=args.loglevel)

    try:
        selected_backend = guess_backend(args.printer)
    except:
        parser.error("Couln't guess the backend to use from the printer string descriptor")
    BACKEND_CLASS = backend_factory(selected_backend)['backend_class']
    BACKEND_STRING_DESCR = args.printer

    MODEL = args.model

    if args.default_label_size not in label_sizes:
        parser.error("Invalid --default-label-size. Please choose on of the following:\n:" + " ".join(label_sizes))
    DEFAULT_LABEL_SIZE  = args.default_label_size
    DEFAULT_ORIENTATION = args.default_orientation

    FONTS = get_fonts()
    if args.font_folder:
        FONTS.update(get_fonts(args.font_folder))

    for font in DEFAULT_FONTS:
        try:
            FONTS[font['family']][font['style']]
            DEFAULT_FONT = font
            logger.debug("Selected the following default font: {}".format(font))
            break
        except: pass
    if DEFAULT_FONT is None:
        sys.stderr.write('Could not find any of the default fonts')
        sys.exit()

    run(host='', port=args.port, debug=DEBUG)

if __name__ == "__main__":
    main()
