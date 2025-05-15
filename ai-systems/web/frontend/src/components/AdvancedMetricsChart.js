import React from 'react';
import {
  ResponsiveContainer,
  AreaChart, Area,
  LineChart, Line,
  BarChart, Bar,
  XAxis, YAxis,
  CartesianGrid,
  Tooltip,
  Legend
} from 'recharts';
import { Box, Paper, Typography, useTheme } from '@mui/material';

/**
 * Advanced metrics chart component with multiple visualization options
 * @param {Object} props - Component props
 * @param {Array} props.data - Chart data
 * @param {String} props.type - Chart type (area, line, bar)
 * @param {String} props.dataKey - Key for data values
 * @param {String} props.xAxisKey - Key for X axis values
 * @param {String} props.title - Chart title
 * @param {String} props.color - Primary color for chart
 * @param {Number} props.height - Chart height
 * @param {Boolean} props.gradient - Whether to use gradient fill
 * @param {Object} props.tooltipFormatter - Function to format tooltip values
 */
const AdvancedMetricsChart = ({
  data = [],
  type = 'area',
  dataKey = 'value',
  xAxisKey = 'timestamp',
  title = 'Metrics',
  color = '#6366f1',
  height = 300,
  gradient = true,
  tooltipFormatter = null,
  syncId = null
}) => {
  const theme = useTheme();
  
  // Custom tooltip component
  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <Paper
          elevation={3}
          sx={{
            p: 1.5,
            backgroundColor: 'rgba(19, 47, 76, 0.9)',
            border: `1px solid ${theme.palette.primary.main}`,
            backdropFilter: 'blur(4px)'
          }}
        >
          <Typography variant="caption" color="text.secondary">
            {label}
          </Typography>
          {payload.map((entry, index) => (
            <Typography
              key={index}
              variant="body2"
              sx={{ color: entry.color, fontWeight: 'bold' }}
            >
              {entry.name}: {tooltipFormatter ? tooltipFormatter(entry.value) : entry.value}
            </Typography>
          ))}
        </Paper>
      );
    }
    return null;
  };

  // Render chart based on type
  const renderChart = () => {
    const commonProps = {
      data,
      syncId,
      margin: { top: 10, right: 30, left: 0, bottom: 0 }
    };

    const gradientId = `color${dataKey}`;

    switch (type) {
      case 'area':
        return (
          <AreaChart {...commonProps}>
            {gradient && (
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={color} stopOpacity={0.8} />
                  <stop offset="95%" stopColor={color} stopOpacity={0.1} />
                </linearGradient>
              </defs>
            )}
            <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
            <XAxis
              dataKey={xAxisKey}
              stroke={theme.palette.text.secondary}
              tick={{ fontSize: 12 }}
            />
            <YAxis
              stroke={theme.palette.text.secondary}
              tick={{ fontSize: 12 }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey={dataKey}
              stroke={color}
              fillOpacity={1}
              fill={gradient ? `url(#${gradientId})` : color}
              activeDot={{ r: 6, strokeWidth: 2, stroke: theme.palette.background.default }}
            />
          </AreaChart>
        );

      case 'line':
        return (
          <LineChart {...commonProps}>
            <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
            <XAxis
              dataKey={xAxisKey}
              stroke={theme.palette.text.secondary}
              tick={{ fontSize: 12 }}
            />
            <YAxis
              stroke={theme.palette.text.secondary}
              tick={{ fontSize: 12 }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Line
              type="monotone"
              dataKey={dataKey}
              stroke={color}
              strokeWidth={2}
              dot={{ r: 4, strokeWidth: 2, stroke: theme.palette.background.default }}
              activeDot={{ r: 6, strokeWidth: 2, stroke: theme.palette.background.default }}
            />
          </LineChart>
        );

      case 'bar':
        return (
          <BarChart {...commonProps}>
            <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
            <XAxis
              dataKey={xAxisKey}
              stroke={theme.palette.text.secondary}
              tick={{ fontSize: 12 }}
            />
            <YAxis
              stroke={theme.palette.text.secondary}
              tick={{ fontSize: 12 }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Bar
              dataKey={dataKey}
              fill={color}
              radius={[4, 4, 0, 0]}
              barSize={20}
              animationDuration={1000}
            />
          </BarChart>
        );

      default:
        return (
          <AreaChart {...commonProps}>
            <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
            <XAxis dataKey={xAxisKey} />
            <YAxis />
            <Tooltip content={<CustomTooltip />} />
            <Area type="monotone" dataKey={dataKey} stroke={color} fill={color} />
          </AreaChart>
        );
    }
  };

  return (
    <Box sx={{ width: '100%', height }}>
      {title && (
        <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 500 }}>
          {title}
        </Typography>
      )}
      <ResponsiveContainer width="100%" height="100%">
        {renderChart()}
      </ResponsiveContainer>
    </Box>
  );
};

export default AdvancedMetricsChart;
