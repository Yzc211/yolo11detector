// detect_gallery.js — 支持：选择图片 / 选择文件夹（分别两按钮），选择即自动上传；results 全宽显示并支持放大
document.addEventListener('DOMContentLoaded', () => {
  const chooseImagesBtn = document.getElementById('chooseImagesBtn');
  const chooseFolderBtn = document.getElementById('chooseFolderBtn');
  const imagesInput = document.getElementById('imagesInput');
  const folderInput = document.getElementById('folderInput');
  const dropArea = document.getElementById('drop-area');
  const detectAllBtn = document.getElementById('detectAllBtn');
  const singleDetectBtn = document.getElementById('singleDetectBtn');
  const status = document.getElementById('status');
  const gallery = document.getElementById('gallery');
  const resultsGrid = document.getElementById('resultsGrid');
  const savedPathInfo = document.getElementById('savedPathInfo');
  const modalImage = document.getElementById('modalImage');
  const imageModalEl = document.getElementById('imageModal');
  const imageModal = new bootstrap.Modal(imageModalEl);

  let stagedFiles = [];
  let selected = null;

  // 绑定两个不同的选择入口
  chooseImagesBtn.addEventListener('click', () => imagesInput.click());
  chooseFolderBtn.addEventListener('click', () => folderInput.click());

  imagesInput.addEventListener('change', async (e) => {
    stagedFiles = Array.from(e.target.files);
    status.innerText = `${stagedFiles.length} 张图片已选择，正在上传...`;
    await uploadSelectedFiles(stagedFiles);
    imagesInput.value = null;
  });

  folderInput.addEventListener('change', async (e) => {
    // 选择文件夹时，浏览器会把文件夹内所有文件（包含相对路径 webkitRelativePath）放到 files 列表
    stagedFiles = Array.from(e.target.files);
    status.innerText = `${stagedFiles.length} 张图片（来自文件夹）已选择，正在上传...`;
    await uploadSelectedFiles(stagedFiles);
    folderInput.value = null;
  });

  // 拖拽支持（拖入后也会立即上传）
  ['dragenter','dragover'].forEach(ev => {
    dropArea.addEventListener(ev, e => { e.preventDefault(); dropArea.classList.add('dragover'); });
  });
  ['dragleave','drop'].forEach(ev => {
    dropArea.addEventListener(ev, e => { e.preventDefault(); dropArea.classList.remove('dragover'); });
  });
  dropArea.addEventListener('drop', async (e) => {
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
    if (files.length) {
      status.innerText = `${files.length} 张图片已拖入，正在上传...`;
      await uploadSelectedFiles(files);
    }
  });

  // 上传并保存（自动触发）：把文件列表 POST 到 /upload_images
  async function uploadSelectedFiles(files) {
    if (!files || files.length === 0) {
      status.innerText = '未检测到文件';
      return;
    }
    try {
      const fd = new FormData();
      files.forEach(f => fd.append('files', f, f.webkitRelativePath || f.name));
      const r = await fetch('/upload_images', { method: 'POST', body: fd });
      const j = await r.json();
      if (!r.ok) {
        status.innerText = '上传失败: ' + (j.error || JSON.stringify(j));
        return;
      }
      // 刷新已上传缩略图
      await loadGallery();
      // 上传不触发检测，清除 savedPathInfo
      showSavedPathInfo('');
      status.innerText = `上传完成：已保存 ${j.saved ? j.saved.length : 0} 张`;
    } catch (e) {
      status.innerText = '上传请求失败: ' + e;
    }
  }

  // 加载已上传缩略图
  async function loadGallery() {
    gallery.innerHTML = '';
    singleDetectBtn.disabled = true;
    selected = null;
    try {
      const r = await fetch('/list_uploads');
      const j = await r.json();
      const files = j.files || [];
      if (files.length === 0) {
        gallery.innerHTML = '<div class="text-muted small p-2">还没有上传图片</div>';
        return;
      }
      files.forEach(name => {
        const col = document.createElement('div');
        col.className = 'col';
        const thumb = document.createElement('div');
        thumb.className = 'thumb card p-0';
        const img = document.createElement('img');
        img.src = `/uploads/${encodeURIComponent(name)}`;
        img.alt = name;
        thumb.appendChild(img);
        col.appendChild(thumb);
        gallery.appendChild(col);

        thumb.addEventListener('click', () => {
          document.querySelectorAll('#gallery .thumb').forEach(t => t.classList.remove('selected'));
          thumb.classList.add('selected');
          selected = name;
          singleDetectBtn.disabled = false;
        });
      });
    } catch (e) {
      gallery.innerHTML = '<div class="text-danger small">无法加载已上传图片</div>';
    }
  }

  // 渲染结果网格（每个 url 显示一个缩略图，点击可放大）
  function renderResultsGridFromUrls(urls) {
    resultsGrid.innerHTML = '';
    if (!urls || urls.length === 0) {
      resultsGrid.innerHTML = '<div class="text-muted small p-2">没有检测结果图片。</div>';
      return;
    }
    urls.forEach(u => {
      const col = document.createElement('div');
      col.className = 'col-6 col-md-4 col-lg-3';
      const card = document.createElement('div');
      card.className = 'card thumb p-1';
      const img = document.createElement('img');
      img.src = u;
      img.className = 'img-fluid rounded';
      img.style.cursor = 'pointer';
      img.addEventListener('click', () => {
        modalImage.src = u;
        imageModal.show();
      });
      card.appendChild(img);
      col.appendChild(card);
      resultsGrid.appendChild(col);
    });
  }

  // 显示“结果已保存至 XX 路径下”的提示
  function showSavedPathInfo(text) {
    if (!savedPathInfo) return;
    if (!text) {
      savedPathInfo.innerHTML = '';
      return;
    }
    const escaped = String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    savedPathInfo.innerHTML = `结果已保存至：<code>${escaped}</code>`;
  }

  // 单张检测（基于已上传列表中选中的图片）
  singleDetectBtn.addEventListener('click', async () => {
    if (!selected) return;
    singleDetectBtn.disabled = true;
    singleDetectBtn.innerText = '检测中...';
    status.innerText = `正在对 ${selected} 进行检测...`;
    try {
      const r = await fetch('/detect_one', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: selected })
      });
      const j = await r.json();
      if (!r.ok) {
        status.innerText = '检测失败: ' + (j.error || JSON.stringify(j));
        showSavedPathInfo('');
        return;
      }
      if (j.results && j.results.length) {
        renderResultsGridFromUrls(j.results);
        // 显示保存路径（优先显示相对路径 saved_dir）
        if (j.saved_dir) showSavedPathInfo(j.saved_dir);
        else if (j.saved_dir_abs) showSavedPathInfo(j.saved_dir_abs);
        else showSavedPathInfo('');
        status.innerText = '单张检测完成（显示所有生成的带框图片）';
      } else if (j.result_image) {
        renderResultsGridFromUrls([j.result_image]);
        if (j.saved_dir) showSavedPathInfo(j.saved_dir);
        else if (j.saved_dir_abs) showSavedPathInfo(j.saved_dir_abs);
        else showSavedPathInfo('');
        status.innerText = '单张检测完成';
      } else {
        showSavedPathInfo('');
        status.innerText = '单张检测完成，但未生成带框图像';
      }
    } catch (e) {
      status.innerText = '检测请求失败: ' + e;
      showSavedPathInfo('');
    } finally {
      singleDetectBtn.disabled = false;
      singleDetectBtn.innerText = '单张检测';
    }
  });

  // 全部检测（对所有已上传图片）
  detectAllBtn.addEventListener('click', async () => {
    detectAllBtn.disabled = true;
    detectAllBtn.innerText = '全部检测中...';
    status.innerText = '正在对所有已上传图片进行检测（可能较慢）...';
    try {
      const r = await fetch('/detect_all', { method: 'POST' });
      const j = await r.json();
      if (!r.ok) {
        status.innerText = '批量检测失败: ' + (j.error || JSON.stringify(j));
        showSavedPathInfo('');
        return;
      }
      // j.results 是数组，每项 {filename, results: [...]}，把所有结果平铺展示
      const allUrls = [];
      if (Array.isArray(j.results)) {
        j.results.forEach(item => {
          if (Array.isArray(item.results) && item.results.length) {
            item.results.forEach(u => allUrls.push(u));
          } else if (item.result_image) {
            allUrls.push(item.result_image);
          }
        });
      }
      if (allUrls.length) {
        renderResultsGridFromUrls(allUrls);
        // 显示 batch_dirs（如果存在），否则尝试从第一个 item 中读取 saved_dir
        if (j.batch_dirs && j.batch_dirs.length) {
          showSavedPathInfo(j.batch_dirs.join('; '));
        } else {
          const sd = (j.results && j.results.length && (j.results[0].saved_dir || j.results[0].saved_dir_abs)) ? (j.results[0].saved_dir || j.results[0].saved_dir_abs) : '';
          showSavedPathInfo(sd);
        }
        status.innerText = `全部检测完成，共处理 ${j.results.length} 张，生成 ${allUrls.length} 张结果图`;
      } else {
        renderResultsGridFromUrls([]);
        showSavedPathInfo('');
        status.innerText = '全部检测完成，但未生成带框图像';
      }
    } catch (e) {
      status.innerText = '批量检测请求失败: ' + e;
      showSavedPathInfo('');
    } finally {
      detectAllBtn.disabled = false;
      detectAllBtn.innerText = '全部检测';
      await loadGallery();
    }
  });

  // 初始加载
  loadGallery();
});