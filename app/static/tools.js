// Every tool on the page is described here; app.js turns these into the UI.
// Option types: tickets (big choice cards), range, number, text, select, color.
// `show(v, s)` decides when an option appears (v = chosen values, s = state).

const IMG = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tif', 'tiff', 'heic', 'heif', 'ico'];
const PDF = ['pdf'];
const DOC = ['docx', 'doc', 'odt', 'rtf'];
const VID = ['mp4', 'mov', 'm4v', 'webm', 'mkv', 'avi', '3gp', 'mpeg', 'mpg'];

const IMG_HINT = 'PNG, JPG, WEBP, HEIC, GIF, BMP or TIFF';

const LEVELS = [
  { value: 'light', title: 'Light', note: 'Best quality, smaller file.' },
  { value: 'balanced', title: 'Balanced', note: 'Much smaller, still looks the same.' },
  { value: 'strong', title: 'Strong', note: 'Smallest file. Some quality loss.' },
  { value: 'target', title: 'Exact size', note: 'Get under a limit, like 200 KB.' },
];

const PRESETS = {
  passport: [413, 531, 'cover'],
  'ig-square': [1080, 1080, 'cover'],
  'ig-portrait': [1080, 1350, 'cover'],
  story: [1080, 1920, 'cover'],
  'yt-thumb': [1280, 720, 'cover'],
  'wa-dp': [500, 500, 'cover'],
};

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

window.TOOLS = [
  /* ------------------------------------------------------------ convert */
  {
    id: 'convert', group: 'Convert', nav: 'Change format',
    title: 'Change file format',
    blurb: 'Turn images and PDFs into the format you need: PNG to JPG, PDF to images, photos to a PDF.',
    endpoint: '/api/convert', exts: [...IMG, ...PDF], multiple: true, maxFiles: 20, maxMB: 25,
    hint: `${IMG_HINT} or PDF. Up to 20 files, 25 MB each.`,
    options: [
      {
        type: 'tickets', name: 'target', label: 'Convert to', big: true, value: 'jpg',
        items: [
          { value: 'jpg', title: 'JPG', note: 'Photos. Small files, works everywhere.' },
          { value: 'png', title: 'PNG', note: 'Screenshots and graphics. Keeps transparency.' },
          { value: 'pdf', title: 'PDF', note: 'Combine images into one document.', disabled: (v, s) => s.hasPdf },
          { value: 'webp', title: 'WEBP', note: 'Smallest size for websites.' },
          { value: 'gif', title: 'GIF', note: 'Simple graphics, old apps.' },
          { value: 'bmp', title: 'BMP', note: 'Uncompressed, for older software.' },
          { value: 'tiff', title: 'TIFF', note: 'Printing and scanning.' },
          { value: 'ico', title: 'ICO', note: 'Website and app icons.' },
        ],
      },
      { type: 'range', name: 'quality', label: 'Image quality', min: 40, max: 100, step: 5, value: 90,
        help: 'Lower makes smaller files. 90 looks the same as the original to most people.',
        show: (v) => ['jpg', 'webp'].includes(v.target) },
      { type: 'select', name: 'dpi', label: 'PDF page sharpness', value: '150',
        items: [['100', 'Screen (smaller files)'], ['150', 'Standard'], ['300', 'Print (sharpest, larger files)']],
        help: 'Used when turning PDF pages into images.', show: (v, s) => s.hasPdf || v.target === 'pdf' },
    ],
    action: (v, s) => (v.target === 'pdf'
      ? `Combine ${plural(s.count, 'image')} into a PDF`
      : `Convert ${plural(s.count, 'file')} to ${v.target.toUpperCase()}`),
  },

  /* ------------------------------------------------------------ images */
  {
    id: 'compress-image', group: 'Images', nav: 'Compress',
    title: 'Compress images',
    blurb: 'Make photos smaller for email, WhatsApp or upload forms. Location and camera details are removed too.',
    endpoint: '/api/image/compress', exts: IMG, multiple: true, maxFiles: 20, maxMB: 25,
    hint: `${IMG_HINT}. Up to 20 files, 25 MB each.`,
    options: [
      { type: 'tickets', name: 'level', label: 'How much smaller', value: 'balanced', items: LEVELS },
      { type: 'number', name: 'target_kb', label: 'Keep each image under', suffix: 'KB', value: 200, min: 10, max: 20000,
        quick: [50, 100, 200, 500], help: 'Images may be scaled down a little to fit.', show: (v) => v.level === 'target' },
    ],
    fields: (v) => ({ level: v.level === 'target' ? 'balanced' : v.level, target_kb: v.level === 'target' ? v.target_kb : 0 }),
    action: (v, s) => `Compress ${plural(s.count, 'image')}`,
  },
  {
    id: 'resize', group: 'Images', nav: 'Resize',
    title: 'Resize images',
    blurb: 'Set an exact size in pixels, scale by percentage, or pick a ready-made size for forms and social media.',
    endpoint: '/api/image/resize', exts: IMG, multiple: true, maxFiles: 20, maxMB: 25,
    hint: `${IMG_HINT}. Up to 20 files, 25 MB each.`,
    options: [
      {
        type: 'tickets', name: 'preset', label: 'Size', value: 'custom',
        items: [
          { value: 'custom', title: 'Custom', note: 'Type the width and height.' },
          { value: 'percent', title: 'Percentage', note: 'Scale up or down, like 50%.' },
          { value: 'passport', title: 'Passport', note: '35 × 45 mm at print quality.' },
          { value: 'ig-square', title: 'Instagram post', note: '1080 × 1080 square.' },
          { value: 'ig-portrait', title: 'Instagram portrait', note: '1080 × 1350.' },
          { value: 'story', title: 'Story or reel', note: '1080 × 1920.' },
          { value: 'yt-thumb', title: 'YouTube thumbnail', note: '1280 × 720.' },
          { value: 'wa-dp', title: 'Profile photo', note: '500 × 500 for WhatsApp and others.' },
        ],
      },
      { type: 'number', name: 'width', label: 'Width', suffix: 'px', value: '', min: 1, max: 10000,
        help: 'Leave one side empty to keep the shape.', show: (v) => v.preset === 'custom' },
      { type: 'number', name: 'height', label: 'Height', suffix: 'px', value: '', min: 1, max: 10000,
        show: (v) => v.preset === 'custom' },
      { type: 'select', name: 'fit', label: 'When both are set', value: 'contain',
        items: [['contain', 'Fit inside, keep the whole picture'], ['cover', 'Fill exactly, trim the edges'], ['stretch', 'Stretch to fit']],
        show: (v) => v.preset === 'custom' && v.width && v.height },
      { type: 'range', name: 'percent', label: 'Scale', suffix: '%', min: 10, max: 200, step: 5, value: 50,
        show: (v) => v.preset === 'percent' },
    ],
    fields: (v) => {
      if (v.preset === 'percent') return { percent: v.percent };
      if (PRESETS[v.preset]) { const [w, h, fit] = PRESETS[v.preset]; return { width: w, height: h, fit }; }
      return { width: v.width || 0, height: v.height || 0, fit: v.fit };
    },
    ready: (v) => v.preset !== 'custom' || v.width || v.height,
    notReady: 'Enter a width or height',
    action: (v, s) => `Resize ${plural(s.count, 'image')}`,
  },
  {
    id: 'crop-rotate', group: 'Images', nav: 'Crop and rotate',
    title: 'Crop and rotate',
    blurb: 'Fix sideways photos, mirror them, or trim to a square or another shape. Cropping keeps the centre.',
    endpoint: '/api/image/crop-rotate', exts: IMG, multiple: true, maxFiles: 20, maxMB: 25,
    hint: `${IMG_HINT}. Up to 20 files, 25 MB each.`,
    options: [
      {
        type: 'tickets', name: 'rotate', label: 'Rotate', value: '0', compact: true,
        items: [
          { value: '0', title: 'None' }, { value: '90', title: 'Right', note: 'Quarter turn clockwise.' },
          { value: '180', title: 'Upside down' }, { value: '270', title: 'Left', note: 'Quarter turn anticlockwise.' },
        ],
      },
      {
        type: 'tickets', name: 'ratio', label: 'Crop to', value: 'original', compact: true,
        items: [
          { value: 'original', title: 'No crop' }, { value: '1:1', title: 'Square' },
          { value: '4:5', title: '4:5', note: 'Instagram portrait.' }, { value: '16:9', title: '16:9', note: 'Widescreen.' },
          { value: '9:16', title: '9:16', note: 'Phone screen.' }, { value: '4:3', title: '4:3', note: 'Classic photo.' },
        ],
      },
      { type: 'select', name: 'flip', label: 'Mirror', value: 'none',
        items: [['none', 'No'], ['horizontal', 'Left to right'], ['vertical', 'Top to bottom']] },
    ],
    ready: (v) => v.rotate !== '0' || v.ratio !== 'original' || v.flip !== 'none',
    notReady: 'Choose a rotation or crop',
    action: (v, s) => `Save ${plural(s.count, 'image')}`,
  },
  {
    id: 'remove-metadata', group: 'Images', nav: 'Remove location data',
    title: 'Remove location and camera details',
    blurb: 'Phone photos can contain the exact place they were taken. Remove it, along with the camera and date, before you share.',
    endpoint: '/api/image/remove-metadata', exts: IMG, multiple: true, maxFiles: 20, maxMB: 25,
    hint: `${IMG_HINT}. Up to 20 files, 25 MB each.`,
    options: [],
    action: (v, s) => `Clean ${plural(s.count, 'photo')}`,
  },
  {
    id: 'favicon', group: 'Images', nav: 'Favicon maker',
    title: 'Favicon maker',
    blurb: 'Turn a logo into every icon size a website needs, with the HTML to paste into your page.',
    endpoint: '/api/image/favicon', exts: IMG, multiple: false, maxFiles: 1, maxMB: 25,
    hint: 'One square-ish logo, ideally 512 × 512 or larger. PNG with a transparent background works best.',
    options: [],
    action: () => 'Make favicon set',
  },

  /* ------------------------------------------------------------ PDF */
  {
    id: 'merge-pdf', group: 'PDF', nav: 'Merge',
    title: 'Merge PDFs',
    blurb: 'Combine several PDFs into one. Use the arrows to set the order.',
    endpoint: '/api/pdf/merge', exts: PDF, multiple: true, ordered: true, minFiles: 2, maxFiles: 30, maxMB: 25,
    hint: 'Two or more PDFs. Up to 30 files, 25 MB each.',
    options: [],
    action: (v, s) => (s.count < 2 ? 'Add at least two PDFs' : `Merge ${s.count} PDFs`),
  },
  {
    id: 'split-pdf', group: 'PDF', nav: 'Split',
    title: 'Split a PDF',
    blurb: 'Keep only the pages you need, or save every page as its own PDF.',
    endpoint: '/api/pdf/split', exts: PDF, multiple: false, maxFiles: 1, maxMB: 50,
    hint: 'One PDF, up to 50 MB.',
    options: [
      {
        type: 'tickets', name: 'mode', label: 'What to do', value: 'extract',
        items: [
          { value: 'extract', title: 'Pick pages', note: 'Make one PDF from the pages you choose.' },
          { value: 'every', title: 'Every page', note: 'One PDF per page, in a zip.' },
        ],
      },
      { type: 'text', name: 'ranges', label: 'Pages to keep', value: '', placeholder: '1-3, 5, 8-',
        help: 'Use commas and dashes. "8-" means page 8 to the end.', show: (v) => v.mode === 'extract' },
    ],
    ready: (v) => v.mode === 'every' || (v.ranges || '').trim(),
    notReady: 'Enter the pages to keep',
    action: (v) => (v.mode === 'every' ? 'Split into single pages' : 'Make the new PDF'),
  },
  {
    id: 'compress-pdf', group: 'PDF', nav: 'Compress',
    title: 'Compress a PDF',
    blurb: 'Shrink scanned PDFs to fit upload limits on job and government portals.',
    endpoint: '/api/pdf/compress', exts: PDF, multiple: false, maxFiles: 1, maxMB: 50,
    hint: 'One PDF, up to 50 MB.',
    options: [
      { type: 'tickets', name: 'level', label: 'How much smaller', value: 'balanced', items: LEVELS },
      { type: 'number', name: 'target_kb', label: 'Keep it under', suffix: 'KB', value: 1024, min: 50, max: 50000,
        quick: [200, 500, 1024, 2048], help: 'Common portal limits are 200 KB, 500 KB, 1 MB and 2 MB.',
        show: (v) => v.level === 'target' },
    ],
    fields: (v) => ({ level: v.level === 'target' ? 'balanced' : v.level, target_kb: v.level === 'target' ? v.target_kb : 0 }),
    action: () => 'Compress PDF',
  },
  {
    id: 'word-to-pdf', group: 'PDF', nav: 'Word to PDF',
    title: 'Word to PDF',
    blurb: 'Turn a Word document into a PDF that looks the same on every device.',
    endpoint: '/api/pdf/from-word', exts: DOC, multiple: false, maxFiles: 1, maxMB: 20, heavy: true,
    hint: 'One .docx, .doc, .odt or .rtf file, up to 20 MB.',
    options: [],
    action: () => 'Convert to PDF',
  },

  /* ------------------------------------------------------------ video */
  {
    id: 'video-mp3', group: 'Video', nav: 'Video to MP3',
    title: 'Video to MP3',
    blurb: 'Pull the sound out of a video and save it as an MP3.',
    endpoint: '/api/video', fixed: { action: 'mp3' }, exts: VID, multiple: false, maxFiles: 1, maxMB: 100, heavy: true,
    hint: 'One video you made or own: MP4, MOV, WEBM, MKV or AVI. Up to 100 MB and 10 minutes.',
    options: [],
    action: () => 'Save as MP3',
  },
  {
    id: 'video-gif', group: 'Video', nav: 'Video to GIF',
    title: 'Video to GIF',
    blurb: 'Turn a short moment from a video into a looping GIF.',
    endpoint: '/api/video', fixed: { action: 'gif' }, exts: VID, multiple: false, maxFiles: 1, maxMB: 100, heavy: true,
    hint: 'One video: MP4, MOV, WEBM, MKV or AVI. Up to 100 MB.',
    options: [
      { type: 'number', name: 'start', label: 'Start at', suffix: 'seconds', value: 0, min: 0, max: 600 },
      { type: 'range', name: 'length', label: 'Length', suffix: ' sec', min: 1, max: 15, step: 1, value: 5 },
      {
        type: 'tickets', name: 'width', label: 'Width', value: '480', compact: true,
        items: [{ value: '320', title: 'Small', note: '320 px' }, { value: '480', title: 'Medium', note: '480 px' }, { value: '640', title: 'Large', note: '640 px' }],
      },
    ],
    action: () => 'Make GIF',
  },
  {
    id: 'video-compress', group: 'Video', nav: 'Compress video',
    title: 'Compress a video',
    blurb: 'Make a video small enough to send on WhatsApp or by email.',
    endpoint: '/api/video', fixed: { action: 'compress' }, exts: VID, multiple: false, maxFiles: 1, maxMB: 100, heavy: true,
    hint: 'One video: MP4, MOV, WEBM, MKV or AVI. Up to 100 MB and 10 minutes.',
    options: [
      { type: 'tickets', name: 'level', label: 'How much smaller', value: 'balanced', items: [
        { value: 'light', title: 'Light', note: 'Full HD, best quality.' },
        { value: 'balanced', title: 'Balanced', note: '720p. Good for sharing.' },
        { value: 'strong', title: 'Strong', note: '480p. Smallest file.' },
      ] },
    ],
    action: () => 'Compress video',
  },
  {
    id: 'video-mp4', group: 'Video', nav: 'Convert to MP4',
    title: 'Convert to MP4',
    blurb: 'Turn iPhone MOV files and other videos into MP4, which plays on every phone, computer and website.',
    endpoint: '/api/video', fixed: { action: 'mp4' }, exts: VID, multiple: false, maxFiles: 1, maxMB: 100, heavy: true,
    hint: 'One video: MOV, WEBM, MKV, AVI or 3GP. Up to 100 MB and 10 minutes.',
    options: [],
    action: () => 'Convert to MP4',
  },

  /* ------------------------------------------------------------ text & codes */
  {
    id: 'ocr', group: 'Text and codes', nav: 'Text from image',
    title: 'Copy text from an image',
    blurb: 'Get the words out of a photo, screenshot or scanned PDF so you can copy and edit them.',
    endpoint: '/api/ocr', exts: [...IMG, ...PDF], multiple: true, maxFiles: 10, maxMB: 25, heavy: true, result: 'text',
    hint: `${IMG_HINT}, or a scanned PDF up to 20 pages.`,
    options: [
      { type: 'select', name: 'lang', label: 'Language in the image', value: 'eng',
        items: [['eng', 'English'], ['tam', 'Tamil'], ['hin', 'Hindi'], ['eng+tam', 'English and Tamil'], ['eng+hin', 'English and Hindi']] },
    ],
    action: () => 'Get the text',
  },
  {
    id: 'qr', group: 'Text and codes', nav: 'QR code maker',
    title: 'QR code maker',
    blurb: 'Make a QR code for a link, a message, your Wi-Fi, or UPI payments.',
    endpoint: '/api/qr', noFiles: true, result: 'qr',
    options: [
      {
        type: 'tickets', name: 'kind', label: 'What it opens', value: 'link', compact: true,
        items: [
          { value: 'link', title: 'Link', note: 'A website or page.' },
          { value: 'text', title: 'Text', note: 'Any message.' },
          { value: 'wifi', title: 'Wi-Fi', note: 'Guests join with one scan.' },
          { value: 'upi', title: 'UPI payment', note: 'Paid with GPay, PhonePe or Paytm.' },
        ],
      },
      { type: 'text', name: 'text', label: 'Link', placeholder: 'https://', value: '', show: (v) => v.kind === 'link' },
      { type: 'textarea', name: 'text', label: 'Message', value: '', show: (v) => v.kind === 'text' },
      { type: 'text', name: 'ssid', label: 'Wi-Fi name', value: '', show: (v) => v.kind === 'wifi' },
      { type: 'text', name: 'password', label: 'Wi-Fi password', value: '', help: 'Leave empty for an open network.', show: (v) => v.kind === 'wifi' },
      { type: 'select', name: 'security', label: 'Security', value: 'WPA', items: [['WPA', 'WPA or WPA2 (most common)'], ['WEP', 'WEP (older routers)']],
        show: (v) => v.kind === 'wifi' && v.password },
      { type: 'text', name: 'upi', label: 'UPI ID', placeholder: 'name@okbank', value: '', show: (v) => v.kind === 'upi' },
      { type: 'text', name: 'payee', label: 'Name shown to the payer', value: '', show: (v) => v.kind === 'upi' },
      { type: 'text', name: 'amount', label: 'Amount in ₹', value: '', help: 'Leave empty to let the payer type it.', inputmode: 'decimal', show: (v) => v.kind === 'upi' },
      { type: 'text', name: 'note', label: 'Note', value: '', help: 'Optional, like "Order 42".', show: (v) => v.kind === 'upi' },
      { type: 'color', name: 'color', label: 'Colour', value: '#17203a', help: 'Keep it dark so phones can scan it.' },
      { type: 'tickets', name: 'fmt', label: 'File type', value: 'png', compact: true, items: [
        { value: 'png', title: 'PNG', note: 'For phones, WhatsApp, printing.' },
        { value: 'svg', title: 'SVG', note: 'Sharp at any size, for designers.' },
      ] },
    ],
    // Two inputs share the name "text"; only send the visible one.
    ready: (v) => ({ link: v.text, text: v.text, wifi: v.ssid, upi: v.upi })[v.kind],
    notReady: 'Fill in the details first',
    action: () => 'Make QR code',
  },
];
