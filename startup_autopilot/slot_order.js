// 只操作当前组件的轨道；用户文本通过textContent插入。
export function moveOrder(ids, source, target) {
    const order = [...ids];
    const from = order.indexOf(source), to = order.indexOf(target);
    if (from < 0 || to < 0 || from === to) return order;
    order.splice(from, 1);
    order.splice(to, 0, source);
    return order;
}

export default function(component) {
    const {data, parentElement, setTriggerValue} = component;
    const track = parentElement.querySelector('.slot-track');
    track.replaceChildren();
    let dragging = null;
    const ids = data.slots.map(s => s.slot_id);
    const send = (source, target) => setTriggerValue('reordered', {
        order: moveOrder(ids, source, target), revision: data.revision
    });
    for (const [index, slot] of data.slots.entries()) {
        const row = document.createElement('div');
        row.className = 'slot-order-row'; row.draggable = true; row.tabIndex = 0;
        row.setAttribute('role','listitem');
        row.setAttribute('aria-label', `第${index + 1}段，${slot.label}。可拖动，或按Alt加上下箭头调整。`);
        const grip = document.createElement('span'); grip.textContent = '⠿'; grip.className = 'grip';
        const number = document.createElement('span'); number.textContent = String(index + 1); number.className = 'slot-number';
        const title = document.createElement('strong'); title.textContent = slot.label;
        const detail = document.createElement('span'); detail.textContent = slot.detail; detail.className = 'slot-detail';
        row.append(grip, number, title, detail);
        row.ondragstart = event => {
            dragging = slot.slot_id; row.classList.add('dragging');
            event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', slot.slot_id);
        };
        row.ondragend = () => { row.classList.remove('dragging'); dragging = null; };
        row.ondragover = event => { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; row.classList.add('drop-target'); };
        row.ondragleave = () => row.classList.remove('drop-target');
        row.ondrop = event => {
            event.preventDefault(); row.classList.remove('drop-target');
            if (dragging && ids.includes(dragging)) send(dragging, slot.slot_id);
        };
        row.onkeydown = event => {
            if (!event.altKey || !['ArrowUp','ArrowDown'].includes(event.key)) return;
            const to = index + (event.key === 'ArrowUp' ? -1 : 1);
            if (to >= 0 && to < ids.length) { event.preventDefault(); send(slot.slot_id, ids[to]); }
        };
        track.appendChild(row);
    }
    return () => track.replaceChildren();
}
