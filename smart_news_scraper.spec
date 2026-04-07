# -*- mode: python ; coding: utf-8 -*-

block_cipher = None


a = Analysis(
    ['gui_main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('config', 'config'),
        ('data', 'data'),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngine',
        'IPython',
        'jedi',
        'matplotlib',
        'pandas',
        'tkinter',
        'torch',
        'torchvision',
        'torchaudio',
        'torchtext',
        'tensorflow',
        'tensorflow_intel',
        'tensorflow_gpu',
        'keras',
        'nvidia',
        'triton',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SmartNewsScraper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='config/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SmartNewsScraper'
)
