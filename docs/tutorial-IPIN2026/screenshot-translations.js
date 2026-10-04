// 在原始截图上叠加可编辑的中文释义；曲线和数值仍来自原截图。
export async function translateScreenshots(root) {
  const response = await fetch('./screenshot-labels.json');
  if (!response.ok) throw new Error('中文截图标注加载失败');
  const labels = await response.json();
  for (const img of root.querySelectorAll('img')) {
    const key = img.getAttribute('src')?.match(/images\/(app-[\w-]+)\.png$/)?.[1];
    if (!labels[key]) continue;
    const { width, height, lines } = labels[key];
    const wrapper = document.createElement('div');
    wrapper.className = 'translated-screenshot';
    wrapper.style.aspectRatio = `${width} / ${height}`;
    img.replaceWith(wrapper);
    wrapper.append(img);
    const measure = document.createElement('canvas').getContext('2d');
    measure.font = '12px "Microsoft YaHei"';
    function add(text, x, y, w, h, rotate = false) {
      const label = document.createElement('span');
      label.className = 'screenshot-translation' + (rotate ? ' screenshot-axis' : '');
      label.textContent = text;
      label.style.cssText = `left:${(x - 2) / width * 100}%;top:${(y - 1) / height * 100}%;width:${(w + 4) / width * 100}%;height:${(h + 3) / height * 100}%;`;
      if (!rotate) label.style.fontSize = `${Math.min(12, 12 * (w + 4) / measure.measureText(text).width) / width * 100}cqw`;
      wrapper.append(label);
    }
    for (const l of lines) add(l.text, l.x, l.y, l.w, l.h);
    if (key === 'app-pbr') {
      add('幅度', 12, 265, 25, 69, true);
      add('折叠相位（rad）', 840, 201, 23, 104, true);
      add('解缠后的乘积相位（rad）', 12, 590, 25, 230, true);
      add('IFFT 幅度', 840, 650, 23, 110, true);
      add('模式 0 校正', 1430, 124, 210, 18);
    } else {
      add('主机日志：警告', 440, 22, 132, 18);
      add('信息', 366, 22, 51, 18);
      if (key === 'app-planner') add('达到配置工作量或过程时间、步骤数限制时结束。', 28, 943, 400, 20);
      if (key === 'app-controller') {
        add('外围设备延迟', 793, 430, 113, 13);
        add('0 个事件', 917, 430, 75, 13);
        add('0 个事件', 1007, 430, 65, 13);
      }
      if (key === 'app-session') {
        add('子事件　报告　客户端日志　主机　对端　其他', 929, 127, 390, 18);
        add('暂停', 1604, 129, 45, 18);
        add('至', 1475, 129, 22, 18);
        add('时间', 24, 351, 27, 12);
      }
    }
    wrapper.setAttribute('role', 'img');
    wrapper.setAttribute('aria-label', img.alt + '；中文标注，保留原始截图数据');
  }
}
