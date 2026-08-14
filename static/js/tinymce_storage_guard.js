/*
 * TinyMCE 8's Silver theme parses its custom-colour localStorage entries
 * without handling malformed values. Older application code can leave a
 * plain value (for example, "admin") under a tinymce-custom-colors-* key,
 * which prevents the editor UI from rendering. Keep valid colour histories
 * and remove only entries that cannot be used by TinyMCE.
 */
(function () {
  'use strict';

  const storageKeyPrefix = 'tinymce-custom-colors-';

  try {
    const invalidKeys = [];

    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (!key || !key.startsWith(storageKeyPrefix)) {
        continue;
      }

      const value = window.localStorage.getItem(key);
      try {
        const colours = JSON.parse(value);
        if (!Array.isArray(colours) || !colours.every((colour) => typeof colour === 'string')) {
          invalidKeys.push(key);
        }
      } catch (error) {
        invalidKeys.push(key);
      }
    }

    invalidKeys.forEach((key) => window.localStorage.removeItem(key));
  } catch (error) {
    // Storage may be unavailable in a privacy-restricted browser. TinyMCE
    // already falls back to an in-memory implementation in that case.
  }
})();
