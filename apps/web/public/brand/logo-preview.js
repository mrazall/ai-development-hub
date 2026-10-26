const sizes = [16, 20, 24, 32, 48, 64, 128];
const file = (size, variant) => {
  const compact = size <= 24 ? '-compact' : '';
  return variant ? `/brand/logo-nodes${compact}-${variant}.svg` : `/brand/logo-nodes${compact}.svg`;
};
const fill = (id, variant, inline) => {
  const row = document.getElementById(id);
  for (const size of sizes) {
    const cell = document.createElement('div');
    cell.className = `cell ${id}`;
    if (inline) {
      // currentColor versions are inlined so they take the text colour of their context.
      fetch(file(size, 'monochrome').replace('-compact-monochrome', '-monochrome-compact'))
        .then((response) => response.text())
        .then((svg) => {
          cell.insertAdjacentHTML('afterbegin', svg.replace('<svg ', `<svg width="${size}" height="${size}" `));
        });
    } else {
      const image = new Image(size, size);
      image.src = file(size, variant);
      image.alt = '';
      cell.append(image);
    }
    cell.append(`${size}`);
    row.append(cell);
  }
};
fill('dark');
fill('light', 'light');
fill('mono-white', null, true);
fill('mono-black', null, true);
