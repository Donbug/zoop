// cytoscape-fcose는 타입 정의를 제공하지 않는다. 확장 등록(cytoscape.use)에 필요한 모양만 선언한다.
declare module "cytoscape-fcose" {
  import type { Ext } from "cytoscape";
  const fcose: Ext;
  export default fcose;
}
