function toolbarMove(ele,e) {
	var osmall = ele.parentNode;
	osmall.style.cursor="move";
	var e = e || window.event;
	if (!osmall.style.position) {
		osmall.style.position = "absolute";
	}
	var rect = osmall.getBoundingClientRect();
	/*用于保存小的div拖拽前的坐标*/
	osmall.startX = e.clientX - rect.left;
	osmall.startY = e.clientY - rect.top;
	osmall.style.left = rect.left + "px";
	osmall.style.top = rect.top + "px";
	/*鼠标的移动事件*/
	document.onmousemove = function(e) {
		var e = e || window.event;
		var viewW = window.innerWidth || document.documentElement.clientWidth || 1200;
		var viewH = window.innerHeight || document.documentElement.clientHeight || 800;
		var minVisible = 56;
		var nextLeft = e.clientX - osmall.startX;
		var nextTop = e.clientY - osmall.startY;

		var minLeft = minVisible - osmall.offsetWidth;
		var maxLeft = viewW - minVisible;
		var minTop = minVisible - osmall.offsetHeight;
		var maxTop = viewH - minVisible;

		if (nextLeft < minLeft) nextLeft = minLeft;
		if (nextLeft > maxLeft) nextLeft = maxLeft;
		if (nextTop < minTop) nextTop = minTop;
		if (nextTop > maxTop) nextTop = maxTop;

		osmall.style.left = nextLeft + "px";
		osmall.style.top = nextTop + "px";
	};
	/*鼠标的抬起事件,终止拖动*/
	document.onmouseup = function() {
		document.onmousemove = null;
		document.onmouseup = null;
		osmall.style.cursor="pointer";
	};
}