# Answer rendering dependencies

`answer-libs.js` contains the browser distributions of:

- [Marked 18.1.0](https://github.com/markedjs/marked), `lib/marked.umd.js` (MIT).
- [DOMPurify 3.4.16](https://github.com/cure53/DOMPurify), `dist/purify.min.js` (Apache-2.0 OR MPL-2.0).

Downloaded from their versioned npm registry tarballs on 2026-10-08. Each tarball was verified against the registry's SHA-512 integrity value before extracting the browser file. Full upstream licenses are retained in `LICENSES.txt`.

These files are served locally, so answering does not depend on a third-party CDN. After upgrading either dependency, run the frontend regression tests and verify sanitization in a browser DOM environment.
