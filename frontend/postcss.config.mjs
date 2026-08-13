/** Tailwind v4 is a PostCSS plugin and needs no `tailwind.config`. The design
    tokens live in `src/app/globals.css` under `@theme`. */
const config = {
  plugins: { "@tailwindcss/postcss": {} },
};

export default config;
