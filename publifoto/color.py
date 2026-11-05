"""Conversión de color con LittleCMS (incluido en Pillow), sin Adobe."""
import io
import os

from PIL import Image, ImageCms

RECURSOS = os.path.join(os.path.dirname(__file__), "recursos")
FOGRA39 = os.path.join(RECURSOS, "CoatedFOGRA39.icc")

_srgb = ImageCms.createProfile("sRGB")
# sin la caché de un píxel de LittleCMS: así una misma transformación se puede usar
# desde varios hilos a la vez (se generan varios productos y jugadores a la vez)
_FLAGS = ImageCms.Flags.BLACKPOINTCOMPENSATION | ImageCms.Flags.NOCACHE
_transformaciones = {}


def perfil_origen(im):
    icc = im.info.get("icc_profile")
    if icc:
        try:
            p = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        except Exception:
            return _srgb
        # el sRGB estándar (el que ponen Lightroom y Photoshop) es el mismo espacio que
        # el de destino: convertir no cambia nada y es lo más lento de cada foto
        if ImageCms.getProfileDescription(p).strip().startswith("sRGB IEC61966-2") and im.mode == "RGB":
            return _srgb
        return p
    return _srgb


def a_rgb(im, origen=None):
    """Pasa la imagen a sRGB respetando su perfil (o el perfil 'origen' dado)."""
    if origen is None and im.mode == "RGB" and not im.info.get("icc_profile"):
        return im
    if im.mode not in ("RGB", "CMYK"):
        im = im.convert("RGB")
    origen = origen or perfil_origen(im)
    if origen is _srgb and im.mode == "RGB":
        return im
    return ImageCms.profileToProfile(im, origen, _srgb, outputMode="RGB",
                                     renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                                     flags=_FLAGS)


def a_cmyk(im):
    """sRGB -> Coated FOGRA39, colorimétrico relativo con compensación de punto negro
    (los mismos ajustes por defecto que usa Photoshop)."""
    if im.mode == "CMYK":
        return im
    im = a_rgb(im)
    clave = "rgb->fogra"
    if clave not in _transformaciones:
        _transformaciones[clave] = ImageCms.buildTransform(
            _srgb, ImageCms.ImageCmsProfile(FOGRA39), "RGB", "CMYK",
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            flags=_FLAGS)
    salida = ImageCms.applyTransform(im, _transformaciones[clave])
    salida.info["icc_profile"] = icc_fogra()
    return salida


def cmyk_a_rgb(im):
    clave = "fogra->rgb"
    if clave not in _transformaciones:
        _transformaciones[clave] = ImageCms.buildTransform(
            ImageCms.ImageCmsProfile(FOGRA39), _srgb, "CMYK", "RGB",
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            flags=_FLAGS)
    return ImageCms.applyTransform(im, _transformaciones[clave])


def icc_fogra():
    with open(FOGRA39, "rb") as f:
        return f.read()


def icc_srgb():
    return ImageCms.ImageCmsProfile(_srgb).tobytes()
