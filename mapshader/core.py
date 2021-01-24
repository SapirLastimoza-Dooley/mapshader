import json

import datashader as ds
import numpy as np
import dask.array as da


import datashader.transfer_functions as tf

import xarray as xr

from xrspatial import hillshade
from xrspatial.classify import quantile

from mapshader.mercator import MercatorTileDefinition
from mapshader.sources import MapSource


import spatialpandas


tile_def = MercatorTileDefinition(x_range=(-20037508.34, 20037508.34),
                                  y_range=(-20037508.34, 20037508.34))


def create_agg(source: MapSource,
               xmin: float = None, ymin: float = None,
               xmax: float = None, ymax: float = None,
               x: float = None, y: float = None,
               z: float = None,
               height: int = 256, width: int = 256):

    if x is not None and y is not None and z is not None:
        xmin, ymin, xmax, ymax = tile_def.get_tile_meters(x, y, z)
    elif xmin is None or xmax is None or ymin is None or ymax is None:
        raise ValueError('extent must be provided to create_agg()')

    xfield = source.xfield
    yfield = source.yfield
    zfield = source.zfield
    agg_func = source.agg_func
    geometry_type = source.geometry_type
    dataset = source.data

    cvs = ds.Canvas(plot_width=width, plot_height=height,
                    x_range=(xmin, xmax), y_range=(ymin, ymax))

    if geometry_type == 'point':
        return point_aggregation(cvs, dataset, xfield, yfield, zfield, agg_func)

    elif geometry_type == 'line':
        return line_aggregation(cvs, dataset, xfield, yfield, zfield, agg_func)

    elif geometry_type == 'polygon':
        return polygon_aggregation(cvs, dataset, zfield, agg_func)

    elif geometry_type == 'raster':

        if z is not None and len(source.overviews) > 0:
            if z < 3:
                dataset = source.overviews[0]
                print('Using overviews 0!')
            elif z < 6:
                dataset = source.overviews[1]
                print('Using overviews 1!')
            elif z < 9:
                dataset = source.overviews[2]
                print('Using overviews 2!')

        return raster_aggregation(cvs, dataset,
                                  agg_func,
                                  padding=source.raster_padding)

    else:
        raise ValueError('Unkown geometry type for {}'.format(dataset['name']))


def point_aggregation(cvs, data, xfield, yfield, zfield, agg_func):
    if zfield:
        return cvs.points(data, xfield, yfield, getattr(ds, agg_func)(zfield))
    else:
        return cvs.points(data, xfield, yfield)


def line_aggregation(cvs, data, xfield, yfield, zfield, agg_func):
    if zfield:
        return cvs.line(data, xfield, yfield,
                        agg=getattr(ds, agg_func)(zfield))
    else:
        return cvs.line(data, xfield, yfield)


def polygon_aggregation(cvs, data, zfield, agg_func):
    if zfield:
        return cvs.polygons(data,
                            'geometry',
                            agg=getattr(ds, agg_func)(zfield))
    else:
        return cvs.polygons(data, 'geometry')


def raster_aggregation(cvs, data, interpolate='linear', span=None, padding=0):

    xmin, xmax = cvs.x_range
    ymin, ymax = cvs.y_range
    xdrange = (xmax - xmin) * (1 + 2 * padding)
    ydrange = (ymax - ymin) * (1 + 2 * padding)
    xsize = cvs.plot_width * (1 + 2 * padding)
    ysize = cvs.plot_height * (1 + 2 * padding)

    if padding > 0:
        new_xmin = xmin - xdrange
        new_ymin = ymin - ydrange
        new_xmax = xmin + xdrange
        new_ymax = xmin + ydrange
    else:
        new_xmin = xmin
        new_ymin = ymin
        new_xmax = xmax
        new_ymax = ymax

    stcvs = ds.Canvas(plot_width=xsize,
                      plot_height=ysize,
                      x_range=(new_xmin, new_xmax),
                      y_range=(new_ymin, new_ymax))

    xs = slice(new_xmin, new_xmax)
    ys = slice(new_ymax, new_ymin)

    if isinstance(data, da.Array):
        data_to_rasterize = data.copy().loc[{'x': xs, 'y': ys}].compute()
    else:
        data_to_rasterize = data.loc[{'x': xs, 'y': ys}]

    if len(data_to_rasterize) == 0:
        raise ValueError('No data to rasterize')

    agg = stcvs.raster(data_to_rasterize, interpolate=interpolate)
    return agg


additional_transforms = {'hillshade': hillshade,
                         'quantile': quantile}

def apply_additional_transforms(source: MapSource, agg: xr.DataArray):
    agg = agg.astype('float64')
    agg.data[agg.data == 0] = np.nan
    for e in source.extras:
        if e in additional_transforms:
            trans = additional_transforms.get(e)
            if trans is not None:
                agg = trans(agg)
            else:
                raise ValueError(f'Invalid transform name {e}')

    return source, agg


def shade_agg(source: MapSource, agg: xr.DataArray, xmin, ymin, xmax, ymax):
    df = source.data
    zfield = source.zfield
    geometry_type = source.geometry_type
    how = source.shade_how
    cmap = source.cmap
    span = source.span

    if isinstance(cmap, dict):
        return tf.shade(agg, color_key=cmap)
    else:
        if span and span == 'min/max' and geometry_type == 'raster':

            # TODO: make this work for dask

            # TODO: don't need to calculate min each time...move into MapSource
            print('Shade Raster with Span ({}, {})'.format(float(df.min().item()),
                                                           float(df.max().item()) + 1))
            img = tf.shade(agg, cmap=cmap,
                           how=how, span=(int(df.min(skipna=True).item()),
                                          int(df.max(skipna=True).item())+1))

            # TODO: don't do this unless we need to...check source.padding
            return img.loc[{'x': slice(xmin, xmax), 'y': slice(ymax, ymin)}]

        elif span and span == 'min/max':
            print('Shade with Span')
            return tf.shade(agg, cmap=cmap, how=how, span=(np.nanmin(df[zfield]),
                                                           np.nanmax(df[zfield])))
        elif isinstance(span, tuple):
            return tf.shade(agg, cmap=cmap, how=how, span=span)
        else:
            print('Shade without Span')
            return tf.shade(agg, cmap=cmap, how=how)


def render_map(source: MapSource,
               xmin: float = None, ymin: float = None,
               xmax: float = None, ymax: float = None,
               x: float = None, y: float = None,
               z: float = None,
               height: int = 256, width: int = 256):

    agg = create_agg(source, xmin, ymin, xmax, ymax, x, y, z, height, width)
    source, agg = apply_additional_transforms(source, agg)
    img = shade_agg(source, agg, xmin, ymin, xmax, ymax)

    # apply dynamic spreading ----------
    if source.dynspread and source.dynspread > 0:
        img = tf.dynspread(img, threshold=1, max_px=int(source.dynspread))

    return img


def render_geojson(source: MapSource):
    if isinstance(source.data, spatialpandas.GeoDataFrame):
        return source.data.to_geopandas().to_json()
    else:
        # TODO: add proper line geojson (core.render_geojson)
        if source.geometry_type in ('line', 'raster'):
            return json.dumps(source.data.to_dict())
        return source.data.to_json()
