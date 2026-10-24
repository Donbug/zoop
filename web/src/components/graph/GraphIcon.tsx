// D-GRP-01/01b: same paths as the original toolbar assets, painted by text color.
// filter-none: the dark theme inverts [data-icon] images; these already follow the text color.
const colorPaths: Record<string, string[]> = {
  sidebar: [
    'M10.2917 1.625H2.70833C2.11002 1.625 1.625 2.11002 1.625 2.70833V10.2917C1.625 10.89 2.11002 11.375 2.70833 11.375H10.2917C10.89 11.375 11.375 10.89 11.375 10.2917V2.70833C11.375 2.11002 10.89 1.625 10.2917 1.625Z',
    'M4.875 1.625V11.375',
  ],
  globe: [
    'M6.5 11.9167C9.49154 11.9167 11.9167 9.49154 11.9167 6.5C11.9167 3.50846 9.49154 1.08333 6.5 1.08333C3.50846 1.08333 1.08333 3.50846 1.08333 6.5C1.08333 9.49154 3.50846 11.9167 6.5 11.9167Z',
    'M4.33333 6.5C4.33333 4.48323 5.10913 2.54375 6.5 1.08333C7.89087 2.54375 8.66667 4.48323 8.66667 6.5C8.66667 8.51677 7.89087 10.4563 6.5 11.9167C5.10913 10.4563 4.33333 8.51677 4.33333 6.5Z',
    'M1.08333 6.5H11.9167',
  ],
  personal: [
    'M9.20833 1.625C9.49565 1.625 9.7712 1.73914 9.97437 1.9423C10.1775 2.14547 10.2917 2.42102 10.2917 2.70833V10.8333C10.2916 10.9282 10.2667 11.0214 10.2193 11.1036C10.172 11.1858 10.1039 11.2541 10.0218 11.3017C9.93979 11.3493 9.84669 11.3745 9.75183 11.3748C9.65698 11.3751 9.5637 11.3505 9.48133 11.3035L7.03733 9.90708C6.87368 9.8136 6.68847 9.76443 6.5 9.76443C6.31153 9.76443 6.12632 9.8136 5.96267 9.90708L3.51867 11.3035C3.4363 11.3505 3.34302 11.3751 3.24817 11.3748C3.15331 11.3745 3.06021 11.3493 2.97816 11.3017C2.89612 11.2541 2.82801 11.1858 2.78066 11.1036C2.7333 11.0214 2.70836 10.9282 2.70833 10.8333V2.70833C2.70833 2.42102 2.82247 2.14547 3.02563 1.9423C3.2288 1.73914 3.50435 1.625 3.79167 1.625H9.20833Z',
  ],
};

export default function GraphIcon({
  name,
  size = 13,
  inheritColor = false,
}: {
  name: string;
  size?: number;
  inheritColor?: boolean;
}) {
  if (inheritColor && colorPaths[name]) {
    return (
      <svg
        aria-hidden="true"
        data-icon
        focusable="false"
        className="shrink-0 filter-none"
        width={size}
        height={size}
        viewBox="0 0 13 13"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.08333}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {colorPaths[name].map((path, index) => (
          <path key={index} d={path} />
        ))}
      </svg>
    );
  }
  return (
    <img
      src={`/graph-assets/${name}.svg`}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      data-icon
      draggable={false}
    />
  );
}
