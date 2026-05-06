

Fetched https://themesbrand.com/velzon/docs/angular/index.html









Fetched https://themesbrand.com/velzon/docs/angular/theme-setup.html

Fetched https://themesbrand.com/velzon/docs/angular/light-mode.html

Fetched https://themesbrand.com/velzon/docs/angular/dark-mode.html

Fetched https://themesbrand.com/velzon/docs/angular/navigation.html

Here is a draft for your design.md, summarizing the Velzon Angular dashboard's design system, themes, and style conventions for building a chatbot page that matches the dashboard/company PRMS website:

---

# Chatbot Page Design Specification (Velzon Angular Dashboard Integration)

## 1. Overview

This design.md outlines the visual and structural guidelines for integrating a chatbot page into a dashboard or PRMS website using the Velzon Angular Admin Template. The goal is to ensure the chatbot page is visually consistent with the rest of the dashboard, leveraging Velzon's themes, color schemes, and UI conventions.

---

## 2. Theme & Layout System

- **Frameworks:** Angular 21.x.x, Bootstrap 5.3.8, SASS/SCSS
- **Theme Engine:** Attribute-based, easily switchable via data attributes or state
- **Modes Supported:** Light, Dark, RTL (Right-to-Left)
- **Layouts:** Vertical, Horizontal, Detached, Semibox, Two Column, Hovered
- **Width:** Fluid & Boxed
- **Sidebar:** Light, Dark, Colored, Background Image, Multiple Sizes (Large, Compact, Small Icon, Icon Hovered)
- **Topbar:** Light & Dark options
- **Position:** Fixed & Scrollable

---

## 3. Color Schemes

### Theme Variants

- Default
- Saas
- Material
- Galaxy
- Corporate
- Minimal
- Creative
- Modern
- Interactive
- Classic
- Vintage

Each theme has its own color palette and style nuances. Choose the one matching your dashboard's current setting.

### Light Mode

- **Background:** #f8f9fa (Bootstrap's light gray)
- **Primary Text:** #212529 (dark gray/black)
- **Sidebar (default):** Dark background with light text
- **Topbar:** Light background with dark text

### Dark Mode

- **Background:** #181c32 or similar dark shades
- **Primary Text:** #f8f9fa (white/light gray)
- **Sidebar (default):** Dark background with lighter accent colors
- **Topbar:** Dark background with light text

### Accent Colors

- **Primary:** #556ee6 (Velzon default blue)
- **Success:** #34c38f (green)
- **Danger:** #f46a6a (red)
- **Warning:** #f1b44c (yellow)
- **Info:** #50a5f1 (light blue)
- **Secondary:** #74788d (gray)
- **Light:** #f8f9fa
- **Dark:** #343a40

> Use Bootstrap variables and Velzon's SCSS variables for consistency.

---

## 4. Typography

- **Font Family:** "Poppins", "Roboto", "Helvetica Neue", Arial, sans-serif
- **Font Sizes:** Responsive, based on Bootstrap's scale (e.g., 1rem, 1.25rem for headings)
- **Font Weight:** 400 (regular), 500 (medium), 600 (semi-bold), 700 (bold)
- **Line Height:** 1.5

---

## 5. UI Components & Structure

- **Card-based Layout:** Use Bootstrap cards for chat containers.
- **Sidebar Navigation:** Consistent with dashboard, collapsible, icons from RemixIcon or similar.
- **Topbar:** Matches dashboard, includes user avatar, notifications, settings.
- **Chat Window:** Rounded corners, subtle box-shadow, padding consistent with dashboard cards.
- **Input Area:** Use Bootstrap input groups, rounded, with send button styled as primary.
- **Avatars:** Circular, 32-40px, with subtle border or shadow.
- **Message Bubbles:** 
  - User: Primary color background, white text.
  - Bot: Light/secondary background, dark text (light mode) or light text (dark mode).
- **Scrollbar:** Custom, thin, matches sidebar style.

---

## 6. Spacing & Sizing

- **Padding:** 1rem (16px) standard for containers
- **Margin:** 1rem between cards/sections
- **Border Radius:** 0.5rem (8px) for cards, chat bubbles, input fields
- **Box Shadow:** Subtle, e.g., 0 2px 8px rgba(0,0,0,0.05)

---

## 7. Responsive Design

- Fully responsive: Mobile, Tablet, Desktop
- Sidebar collapses on mobile
- Chat input and send button stack vertically on small screens

---

## 8. Example Theme Configuration (Angular)

```typescript
export const initialState: LayoutState = {
    LAYOUT: LAYOUT_TYPES.VERTICAL,
    LAYOUT_THEME: LAYOUT_THEME.DEFAULT,
    LAYOUT_THEME_COLOR: LAYOUT_THEME_COLOR.DEFAULT,
    LAYOUT_MODE: LAYOUT_MODE.LIGHTMODE, // or DARKMODE
    LAYOUT_WIDTH: LAYOUT_WIDTH_TYPES.FLUID,
    LAYOUT_POSITION: LAYOUT_POSITION_TYPES.FIXED,
    TOPBAR: LAYOUT_TOPBAR_COLOR_TYPES.LIGHT,
    SIDEBAR_COLOR: SIDEBAR_COLOR.DARK,
    SIDEBAR_SIZE: SIDEBAR_SIZE.LARGE,
    SIDEBAR_VIEW: SIDEBAR_VIEW.DEFAULT,
    SIDEBAR_IMAGE: SIDEBAR_IMAGE.NONE,
    SIDEBAR_VISIBILITY: SIDEBAR_VISIBILITY.SHOW,
    DATA_PRELOADER: PERLOADER_TYPES.DISABLE,
    BACKGROUND_IMAGE: BACKGROUND_IMAGE.NONE,
}
```

---

## 9. Navigation & Menu

- Sidebar menu items defined in `/src/app/layouts/sidebar/menu.ts`
- Use JSON structure for menu items, icons, and nesting
- Example:
  ```json
  {
    "id": "1",
    "label": "Chatbot",
    "icon": "ri-chat-1-line",
    "link": "/chatbot"
  }
  ```

---

## 10. Best Practices

- Use SCSS variables for all colors and spacing
- Inherit dashboard's theme and mode dynamically
- Use Bootstrap utility classes for spacing, alignment, and responsiveness
- Test in both light and dark modes
- Match sidebar and topbar styles for seamless integration

---

**Reference:**  
- Velzon Angular Docs: https://themesbrand.com/velzon/docs/angular/index.html  
- Theme Setup: https://themesbrand.com/velzon/docs/angular/theme-setup.html  
- Light Mode: https://themesbrand.com/velzon/docs/angular/light-mode.html  
- Dark Mode: https://themesbrand.com/velzon/docs/angular/dark-mode.html  
- Navigation: https://themesbrand.com/velzon/docs/angular/navigation.html  

---

This design.md provides a comprehensive foundation for building a chatbot page that visually and structurally matches the Velzon Angular dashboard. For detailed SCSS variables and further customization, refer to the Velzon theme files and documentation.