// 缩写统一在此定义：保留规范中的写法，并提供英文全称与中文释义。
export const terminology = {
  IPIN: ['Indoor Positioning and Indoor Navigation', '室内定位与室内导航'],
  AI: ['Artificial Intelligence', '人工智能'],
  BLE: ['Bluetooth Low Energy', '低功耗蓝牙'],
  LE: ['Low Energy', '低功耗（蓝牙）'],
  CS: ['Channel Sounding', '信道探测'],
  PBR: ['Phase-Based Ranging', '基于相位的测距'],
  RTT: ['Round-Trip Time', '往返时间'],
  'I/Q': ['In-phase / Quadrature', '同相／正交分量'],
  PCT: ['Phase Correction Term', '相位校正项'],
  FFO: ['Fractional Frequency Offset', '相对频偏'],
  FAE: ['Frequency Actuation Error', '频率合成误差'],
  IPT: ['Inline Phase Correction Term Transfer', '内联相位校正项传输'],
  RAS: ['Ranging Service', '测距服务'],
  ACL: ['Asynchronous Connection-oriented Logical Transport', '异步面向连接逻辑传输'],
  LL: ['Link Layer', '链路层'],
  PHY: ['Physical Layer', '物理层'],
  GAP: ['Generic Access Profile', '通用访问配置'],
  GATT: ['Generic Attribute Profile', '通用属性配置'],
  ATT: ['Attribute Protocol', '属性协议'],
  MTU: ['Maximum Transmission Unit', '最大传输单元'],
  PDU: ['Protocol Data Unit', '协议数据单元'],
  L2CAP: ['Logical Link Control and Adaptation Protocol', '逻辑链路控制与适配协议'],
  HCI: ['Host Controller Interface', '主机控制器接口'],
  DRBG: ['Deterministic Random Bit Generator', '确定性随机比特发生器'],
  PRNG: ['Pseudorandom Number Generator', '伪随机数发生器'],
  CSA: ['Channel Selection Algorithm', '信道选择算法'],
  ACI: ['Antenna Configuration Index', '天线配置索引'],
  AP: ['Antenna Path', '天线路径（AP1–AP4 为路径编号）'],
  SE: ['Subevent', '子事件'],
  AA: ['Access Address', '接入地址'],
  ID: ['Identifier', '标识符'],
  LSB: ['Least Significant Bit', '最低有效位'],
  PC: ['Personal Computer', '个人计算机'],
  CTE: ['Constant Tone Extension', '恒定单音扩展'],
  RSSI: ['Received Signal Strength Indicator', '接收信号强度指示'],
  SNR: ['Signal-to-Noise Ratio', '信噪比'],
  ToA: ['Time of Arrival', '到达时间'],
  ToD: ['Time of Departure', '发出时间'],
  ToF: ['Time of Flight', '传播时间'],
  FFT: ['Fast Fourier Transform', '快速傅里叶变换'],
  IFFT: ['Inverse Fast Fourier Transform', '快速傅里叶逆变换'],
  MUSIC: ['Multiple Signal Classification', '多重信号分类算法'],
  ESPRIT: ['Estimation of Signal Parameters via Rotational Invariance Techniques', '基于旋转不变技术的信号参数估计'],
  NADM: ['Normalized Attack Detector Metric', '归一化攻击检测指标'],
  GFSK: ['Gaussian Frequency Shift Keying', '高斯频移键控'],
  LO: ['Local Oscillator', '本地振荡器'],
  RF: ['Radio Frequency', '射频'],
  GNSS: ['Global Navigation Satellite System', '全球导航卫星系统'],
  GPS: ['Global Positioning System', '全球定位系统'],
  UWB: ['Ultra-Wideband', '超宽带'],
  IMU: ['Inertial Measurement Unit', '惯性测量单元'],
  DK: ['Development Kit', '开发套件'],
  SDK: ['Software Development Kit', '软件开发套件'],
  NCS: ['nRF Connect SDK', 'Nordic nRF Connect 软件开发套件'],
  USB: ['Universal Serial Bus', '通用串行总线'],
  CDC: ['Communications Device Class', '通信设备类'],
  ACM: ['Abstract Control Model', '抽象控制模型'],
  UART: ['Universal Asynchronous Receiver/Transmitter', '通用异步收发器'],
  CRC: ['Cyclic Redundancy Check', '循环冗余校验'],
  MIC: ['Message Integrity Check', '消息完整性校验'],
  HDF5: ['Hierarchical Data Format, version 5', '第五版分层数据格式'],
  UI: ['User Interface', '用户界面'],
  API: ['Application Programming Interface', '应用程序编程接口'],
  QR: ['Quick Response', '快速响应二维码'],
  PyPI: ['Python Package Index', 'Python 软件包索引'],
  SIG: ['Special Interest Group', '技术联盟（此处指蓝牙技术联盟）'],
  NHAPS: ['National Human Activity Pattern Survey', '美国全国人类活动模式调查'],
  EPA: ['Environmental Protection Agency', '美国环境保护署'],
  NDSS: ['Network and Distributed System Security Symposium', '网络与分布式系统安全研讨会'],
  CHES: ['Cryptographic Hardware and Embedded Systems', '密码硬件与嵌入式系统会议'],
  MIT: ['Massachusetts Institute of Technology License', 'MIT 开源许可'],
  ppm: ['parts per million', '百万分之一'],
  dB: ['decibel', '分贝'],
  dBm: ['decibel relative to one milliwatt', '以 1 毫瓦为参考的功率分贝'],
  TX: ['Transmit', '发送'],
  RX: ['Receive', '接收'],
  T_IP1: ['Interlude Period 1', '数据包方向切换间隔'],
  T_IP2: ['Interlude Period 2', '单音方向切换间隔'],
  T_FCS: ['Frequency Change Spacing', '频率切换间隔'],
  T_PM: ['Phase Measurement Period', '相位测量时长'],
  T_SW: ['Antenna Switching Period', '天线切换时长'],
  T_IFS: ['Inter Frame Space', '帧间间隔'],
  T_RD: ['Ramp-down Period', '发送功率下降时间'],
  T_GD: ['Guard Period', '保护时间'],
  T_FM: ['Frequency Measurement Period', '频率测量时长'],
};

const keys = Object.keys(terminology).sort((a, b) => b.length - a.length);
const pattern = new RegExp(`(?<![A-Za-z_])(${keys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(?:s)?(?![A-Za-z_])`, 'g');

export function explainAbbreviations(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.parentElement.closest('code, pre, script, style, svg, .notes, a, abbr') && !/\\[([]/.test(node.textContent)) nodes.push(node);
  }
  for (const node of nodes) {
    pattern.lastIndex = 0;
    const matches = [...node.textContent.matchAll(pattern)];
    if (!matches.length) continue;
    const fragment = document.createDocumentFragment();
    let last = 0;
    for (const m of matches) {
      fragment.append(node.textContent.slice(last, m.index));
      const abbr = document.createElement('abbr');
      abbr.textContent = m[0];
      abbr.title = `${terminology[m[1]][0]} · ${terminology[m[1]][1]}`;
      fragment.append(abbr);
      last = m.index + m[0].length;
    }
    fragment.append(node.textContent.slice(last));
    node.replaceWith(fragment);
  }
  // 每页讲者备注同时提供该页所用缩写的完整释义。
  root.querySelectorAll('section[data-file]').forEach(section => {
    const text = section.textContent;
    pattern.lastIndex = 0;
    const used = [...new Set([...text.matchAll(pattern)].map(m => m[1]))];
    if (!used.length) return;
    let notes = section.querySelector('aside.notes');
    if (!notes) { notes = document.createElement('aside'); notes.className = 'notes'; section.append(notes); }
    const p = document.createElement('p');
    p.className = 'terminology-notes';
    p.textContent = '本页缩写：' + used.map(k => `${k} = ${terminology[k][0]}（${terminology[k][1]}）`).join('；');
    notes.append(p);
  });
}

const dialog = document.createElement('dialog');
dialog.className = 'terminology-dialog';
dialog.setAttribute('aria-label', '英文缩写全称与中文释义');
dialog.innerHTML = '<button class="terminology-close" type="button">关闭</button><h2>英文缩写全称与中文释义</h2><p>缩写保留规范原文，术语按本教程语境解释。数据包与参数标识符另列于下方。</p><table><thead><tr><th>缩写</th><th>英文全称</th><th>中文释义</th></tr></thead><tbody></tbody></table>';
const tbody = dialog.querySelector('tbody');
for (const [k, [en, zh]] of Object.entries(terminology)) {
  const row = document.createElement('tr');
  for (const value of [k, en, zh]) { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); }
  tbody.append(row);
}
const p = document.createElement('p');
p.textContent = '协议标识：CS_SYNC 为信道探测同步包；ADV_IND 为广播指示；CONNECT_IND 为连接指示；AUX 表示辅助广播信道；REQ / RSP / IND 分别表示 Request（请求）/ Response（响应）/ Indication（指示）。LL_CS_* 为链路层信道探测控制包；LL_PHY_* 为物理层协商；LL_LENGTH_* 为数据长度协商；LL_ENC_* 和 LL_START_ENC_* 为加密设置及启动；ATT_EXCHANGE_MTU_* 为属性协议最大传输单元交换。No_FAE 表示没有频率合成误差，Config_ID 为配置标识，connEventCount 为连接事件计数。T_* 为规范时序参数，AP1–AP4 为天线路径编号，A1–A4 为定位基站编号。MHz / GHz / kHz 分别为兆赫／吉赫／千赫；ms / µs / ns 为毫秒／微秒／纳秒；m / cm 为米／厘米；B 为字节。品牌、产品型号、软件命令、设备名称和数学变量保留原始写法。';
dialog.append(p);
document.body.append(dialog);
dialog.querySelector('button').onclick = () => dialog.close();
dialog.onclick = e => { if (e.target === dialog) dialog.close(); };
document.getElementById('terminology-button').onclick = () => dialog.showModal();
