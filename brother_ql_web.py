#!/usr/bin/env python

"""
This is a web service to print labels on Brother QL label printers.
"""

import sys, logging, socket, os, functools, textwrap
from io import BytesIO

from bottle import run, route, response, request, jinja2_view as view, static_file, redirect
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
    return {'title': title, 'page_headline': page_headline, 'message': '', 'fonts': fonts, 'label_sizes': label_sizes}

def get_label_context(request):
    """ might raise LookupError() """

    context = {
      'font_size': int(request.query.get('font_size', 100)),
      'font_family':   request.query.get('font_family'),
      'font_style':    request.query.get('font_style'),
      'label_size':    request.query.get('label_size', "62"),
      'margin':    int(request.query.get('margin', 10)),
      'threshold': int(request.query.get('threshold', 70)),
      'align':         request.query.get('align', 'center'),
    }
    context['margin_top']    = int(context['font_size']*0.24)
    context['margin_bottom'] = int(context['font_size']*0.45)

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
    if height == 0:
        height = context['font_size'] + 2 * context['margin']
    if height > width: width, height = height, width

    context['width'], context['height'] = width, height

    return context

def create_label_im(text, **kwargs):
    label_type = label_type_specs[kwargs['label_size']]['kind']
    im_font = ImageFont.truetype(kwargs['font_path'], kwargs['font_size'])
    im = Image.new('L', (20, 20), 'white')
    draw = ImageDraw.Draw(im)
    linesize = im_font.getsize(text)
    textsize = draw.multiline_textsize(text, font=im_font)
    if label_type in (DIE_CUT_LABEL, ROUND_DIE_CUT_LABEL):
        height = kwargs['height']
    else:
        height = textsize[1] + kwargs['margin_top'] + kwargs['margin_bottom']
    im = Image.new('L', (kwargs['width'], height), 'white')
    draw = ImageDraw.Draw(im)
    if label_type in (DIE_CUT_LABEL, ROUND_DIE_CUT_LABEL):
        vertical_offset  = (height - textsize[1])//2
        vertical_offset += (kwargs['margin_top'] - kwargs['margin_bottom'])//2
    else:
        vertical_offset = kwargs['margin_top']
    horizontal_offset = max((kwargs['width'] - textsize[0])//2, 0)
    offset = horizontal_offset, vertical_offset
    draw.multiline_text(offset, text, (0), font=im_font, align=kwargs['align'])
    return im

@route('/api/preview/text/<text>')
def get_preview_image(text):
    context = get_label_context(request)
    image_buffer = BytesIO()
    im = create_label_im(text, **context)
    im.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    response.set_header('Content-type', 'image/png')
    return image_buffer.read()

@route('/api/print/text')
@route('/api/print/text/')
@route('/api/print/text/<content>')
def print_text(content=None):
    """
    API to print a label

    returns: JSON

    Ideas for additional URL parameters:
    - alignment
    """

    return_dict = {'success': False}

    if content is None:
        return_dict['error'] = 'Please provide the text for the label'
        return return_dict

    try:
        context = get_label_context(request)
    except LookupError as e:
        return_dict['error'] = e.msg
        return return_dict

    im = create_label_im(content, **context)
    if DEBUG: im.save('sample-out.png')

    qlr = BrotherQLRaster(MODEL)
    create_label(qlr, im, context['label_size'], threshold=context['threshold'], cut=True)

    if not DEBUG:
        try:
            be = BACKEND_CLASS(BACKEND_STRING_DESCR)
            be.write(qlr.data)
            be.dispose()
            del be
        except Exception as e:
            return_dict['message'] = str(e)
            logger.warning('Exception happened: %s', e)
            response.status = 500
            return return_dict

    return_dict['success'] = True
    if DEBUG: return_dict['data'] = str(qlr.data)
    return return_dict

def main():
    global DEBUG, FONTS, DEFAULT_FONT, MODEL, BACKEND_CLASS, BACKEND_STRING_DESCR
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default=8013)
    parser.add_argument('--loglevel', type=lambda x: getattr(logging, x.upper()), default='WARNING')
    parser.add_argument('--font-folder', help='folder for additional .ttf/.otf fonts')
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
