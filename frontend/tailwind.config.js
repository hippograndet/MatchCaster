/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#0a0a0f',
        surface: '#13131a',
        'surface-2': '#1c1c26',
        pitch: '#1a8a2e',
        'pitch-line': '#ffffff',
        amber: {
          DEFAULT: '#f59e0b',
          dim: '#92610a',
        },
        blue: {
          DEFAULT: '#3b82f6',
          dim: '#1d4ed8',
        },
        emerald: {
          DEFAULT: '#10b981',
          dim: '#065f46',
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
        sans: ['"DM Sans"', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
