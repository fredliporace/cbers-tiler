"""app.cbers: handle request for CBERS-tiler"""

import re
import json
from functools import reduce

import numpy as np
import numexpr as ne

from rio_tiler import cbers
from rio_tiler.utils import array_to_img, linear_rescale, get_colormap

from lambda_proxy.proxy import API

CBERS_APP = API(app_name="cbers-tiler")

RATIOS = {
    'ndvi': {
        'eq': '(b8 - b7) / (b8 + b7)',
        'rg': [-1, 1]}}


class CbersTilerError(Exception):
    """Base exception class"""


@CBERS_APP.route('/cbers/bounds/<scene>', methods=['GET'], cors=True)
def bounds(scene):
    """
    Handle bounds requests
    """
    info = cbers.bounds(scene)
    return ('OK', 'application/json', json.dumps(info))


@CBERS_APP.route('/cbers/metadata/<scene>', methods=['GET'], cors=True)
def metadata(scene):
    """
    Handle metadata requests
    """
    query_args = CBERS_APP.current_request.query_params
    query_args = query_args if isinstance(query_args, dict) else {}

    pmin = query_args.get('pmin', 2)
    pmin = float(pmin) if isinstance(pmin, str) else pmin

    pmax = query_args.get('pmax', 98)
    pmax = float(pmax) if isinstance(pmax, str) else pmax

    info = cbers.metadata(scene, pmin, pmax)
    return ('OK', 'application/json', json.dumps(info))


@CBERS_APP.route('/cbers/tiles/<scene>/<int:z>/<int:x>/<int:y>.<ext>', methods=['GET'], cors=True)
def tile(scene, tile_z, tile_x, tile_y, tileformat):
    """
    Handle tile requests
    """
    query_args = CBERS_APP.current_request.query_params
    query_args = query_args if isinstance(query_args, dict) else {}

    bands = query_args.get('rgb', '7,6,5')
    bands = tuple(re.findall(r'\d+', bands))

    histoCut = query_args.get('histo', ';'.join(['0,255'] * len(bands)))
    histoCut = re.findall(r'\d+,\d+', histoCut)
    histoCut = list(map(lambda x: list(map(int, x.split(','))), histoCut))

    if len(bands) != len(histoCut):
        raise CbersTilerError('The number of bands doesn\'t match the number of histogramm values')

    tilesize = query_args.get('tile', 256)
    tilesize = int(tilesize) if isinstance(tilesize, str) else tilesize

    tile = cbers.tile(scene, tile_x, tile_y, tile_z, bands, tilesize=tilesize)
    rtile = np.zeros((len(bands), tilesize, tilesize), dtype=np.uint8)
    for bdx in range(len(bands)):
        rtile[bdx] = np.where(
            tile[bdx] > 0,
            linear_rescale(tile[bdx], in_range=histoCut[bdx], out_range=[1, 255]), 0)

    tile = array_to_img(rtile, tileformat)
    if tileformat == 'jpg':
        tileformat = 'jpeg'

    return ('OK', f'image/{tileformat}', tile)


@CBERS_APP.route('/cbers/processing/<scene>/<int:z>/<int:x>/<int:y>.<ext>', methods=['GET'], cors=True)
def ratio(scene, tile_z, tile_x, tile_y, tileformat):
    """
    Handle processing requests
    """
    query_args = CBERS_APP.current_request.query_params
    query_args = query_args if isinstance(query_args, dict) else {}

    ratio_value = query_args.get('ratio', 'ndvi')

    if ratio_value not in RATIOS.keys():
        raise CbersTilerError('Invalid ratio: {}'.format(ratio_value))

    equation = RATIOS[ratio_value]['eq']
    band_names = list(set(re.findall('b[0-9]{1,2}', equation)))
    bands = tuple(map(lambda x: x.strip('b'), band_names))

    tilesize = query_args.get('tile', 256)
    tilesize = int(tilesize) if isinstance(tilesize, str) else tilesize

    tile = cbers.tile(scene, tile_x, tile_y, tile_z, bands, tilesize=tilesize)
    for bdx, b in enumerate(band_names):
        globals()[b] = tile[bdx]

    tile = np.where(
        reduce(lambda x, y: x*y, [globals()[i] for i in band_names]) > 0,
        np.nan_to_num(ne.evaluate(equation)),
        -9999)

    range_val = equation = RATIOS[ratio_value]['rg']
    rtile = np.where(
            tile != -9999,
            linear_rescale(tile, in_range=range_val, out_range=[1, 255]), 0).astype(np.uint8)

    tile = array_to_img(rtile, tileformat, color_map=get_colormap(name='cfastie'))
    if tileformat == 'jpg':
        tileformat = 'jpeg'

    return ('OK', f'image/{tileformat}', tile)


@CBERS_APP.route('/favicon.ico', methods=['GET'], cors=True)
def favicon():
    """
    favicon
    """
    return('NOK', 'text/plain', '')
