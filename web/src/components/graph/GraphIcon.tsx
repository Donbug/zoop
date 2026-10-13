export default function GraphIcon({
  name,
  size = 13,
}: {
  name: string;
  size?: number;
}) {
  return (
    <img
      src={`/graph-assets/${name}.svg`}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  );
}
