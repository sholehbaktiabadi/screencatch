desktop_file = files(app_id + '.desktop')
metainfo_file = files(app_id + '.metainfo.xml')
schema_file = files(app_id + '.gschema.xml')

install_data(desktop_file, install_dir: datadir / 'applications')
install_data(metainfo_file, install_dir: datadir / 'metainfo')
install_data(schema_file, install_dir: datadir / 'glib-2.0' / 'schemas')

install_data(
  'icons/app' / app_id + '.svg',
  install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps',
)
install_data(
  'icons/app' / app_id + '-symbolic.svg',
  install_dir: datadir / 'icons' / 'hicolor' / 'symbolic' / 'apps',
)
# Tool icons are private to the app; they are added to the icon theme search path at runtime.
install_subdir(
  'icons/actions',
  install_dir: pkgdatadir / 'icons',
  strip_directory: true,
)

install_man('screencatch.1')

desktop_validate = find_program('desktop-file-validate', required: false)
if desktop_validate.found()
  test('validate-desktop', desktop_validate, args: [desktop_file])
endif

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test('validate-metainfo', appstreamcli, args: ['validate', '--no-net', metainfo_file])
endif

compile_schemas = find_program('glib-compile-schemas', required: false)
if compile_schemas.found()
  test('validate-schema', compile_schemas, args: ['--strict', '--dry-run', meson.current_source_dir()])
endif
