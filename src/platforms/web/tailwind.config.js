/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{vue,js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                primary: {
                    50: '#e6f4fe',
                    100: '#d5efff',
                    200: '#acd8fc',
                    300: '#8ec8f6',
                    400: '#5eb1ef',
                    500: '#0090ff',
                    600: '#0588f0',
                    700: '#0d74ce',
                    800: '#113264',
                    900: '#0d1f3a',
                },
                purple: {
                    start: '#6e56cf',
                    end: '#8b7eff',
                }
            },
        },
    },
    plugins: [],
    // Preflight can conflict with Element Plus, but we'll keep it and handle any issues
    corePlugins: {
        preflight: false, // Disable Tailwind's base reset to avoid conflicts with Element Plus
    },
}
