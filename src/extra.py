#    def analyze_threshold_statistics(self):
#        """
#        Analyze article relevance scores to suggest optimal threshold value
#        using statistical methods.
#
#        Returns:
#            dict: Statistical analysis results and threshold recommendation
#        """
#        try:
#            with self.db_manager.get_connection() as conn:
#                with conn.cursor() as cur:
#                    # Get all relevance scores
#                    cur.execute("""
#                        SELECT relevance_score 
#                        FROM cleaned_articles 
#                        WHERE relevance_score IS NOT NULL
#                    """)
#                    scores = [row[0] for row in cur.fetchall()]
#
#                    if not scores:
#                        raise ValueError("No relevance scores found for analysis")
#
#                    # Calculate basic statistics
#                    scores.sort()
#                    n = len(scores)
#                    mean = sum(scores) / n
#                    median = scores[n//2] if n % 2 else (scores[n//2 - 1] + scores[n//2]) / 2
#
#                    # Calculate quartiles
#                    q1 = scores[n//4]
#                    q3 = scores[3*n//4]
#                    iqr = q3 - q1
#
#                    # Calculate standard deviation
#                    variance = sum((x - mean) ** 2 for x in scores) / n
#                    std_dev = variance ** 0.5
#
#                    # Find natural breaks using k-means-like approach
#                    sorted_scores = sorted(set(scores))  # Unique scores
#                    if len(sorted_scores) > 1:
#                        # Calculate differences between consecutive scores
#                        differences = [
#                            (j - i, i) 
#                            for i, j in zip(sorted_scores[:-1], sorted_scores[1:])
#                        ]
#                        # Find largest gap
#                        max_diff, split_point = max(differences)
#                        natural_threshold = split_point + (max_diff / 2)
#                    else:
#                        natural_threshold = sorted_scores[0]
#
#                    # Calculate suggested thresholds using different methods
#                    suggested_thresholds = {
#                        'mean': mean,
#                        'median': median,
#                        'q3': q3,  # Conservative threshold
#                        'mean_plus_std': mean + std_dev,  # More selective threshold
#                        'natural_break': natural_threshold
#                    }
#
#                    # Analyze impact of each threshold
#                    threshold_impacts = {}
#                    for method, threshold in suggested_thresholds.items():
#                        cur.execute("""
#                            SELECT 
#                                COUNT(CASE WHEN relevance_score >= %s THEN 1 END) as would_include,
#                                COUNT(*) as total
#                            FROM cleaned_articles
#                            WHERE relevance_score IS NOT NULL
#                        """, (threshold,))
#                        include_count, total = cur.fetchone()
#                        threshold_impacts[method] = {
#                            'threshold': round(threshold, 3),
#                            'would_include': include_count,
#                            'would_exclude': total - include_count,
#                            'inclusion_rate': round(include_count / total * 100, 2) if total > 0 else 0
#                        }
#
#                    # Recommend threshold based on distribution and goals
#                    current_threshold = self.RELEVANCE_THRESHOLD
#
#                    # Calculate optimal threshold based on inclusion rate target (e.g., aiming for top 25%)
#                    target_inclusion_rate = 25  # Can be adjusted based on requirements
#                    optimal_threshold = q3  # Start with Q3 as default
#
#                    # Find threshold closest to target inclusion rate
#                    for method, impact in threshold_impacts.items():
#                        if abs(impact['inclusion_rate'] - target_inclusion_rate) < abs(threshold_impacts['q3']['inclusion_rate'] - target_inclusion_rate):
#                            optimal_threshold = impact['threshold']
#
#                    return {
#                        'current_threshold': current_threshold,
#                        'statistical_analysis': {
#                            'mean': round(mean, 3),
#                            'median': round(median, 3),
#                            'std_dev': round(std_dev, 3),
#                            'q1': round(q1, 3),
#                            'q3': round(q3, 3),
#                            'iqr': round(iqr, 3)
#                        },
#                        'threshold_impacts': threshold_impacts,
#                        'recommendation': {
#                            'optimal_threshold': round(optimal_threshold, 3),
#                            'reason': f"Based on target inclusion rate of {target_inclusion_rate}%",
#                            'expected_impact': threshold_impacts['q3']
#                        }
#                    }
#
#        except Exception as e:
#            logging.error(f"Error analyzing threshold statistics: {e}")
#            raise
#
#    def get_threshold_recommendation(self):
#        """
#        Get a recommendation for whether the threshold should be adjusted
#        based on statistical analysis.
#
#        Returns:
#            dict: Recommendation including whether to change threshold and why
#        """
#        try:
#            stats = self.analyze_threshold_statistics()
#            current = self.RELEVANCE_THRESHOLD
#            recommended = stats['recommendation']['optimal_threshold']
#
#            # Define significance threshold for change (e.g., 10% difference)
#            significance_threshold = 0.1
#
#            if abs(current - recommended) / current > significance_threshold:
#                recommendation = {
#                    'should_change': True,
#                    'current_threshold': current,
#                    'recommended_threshold': recommended,
#                    'expected_impact': stats['threshold_impacts']['q3'],
#                    'reason': (
#                        f"Current threshold ({current}) differs significantly "
#                        f"from optimal threshold ({recommended}). "
#                        f"Change would affect article inclusion rate by "
#                        f"{abs(stats['threshold_impacts']['q3']['inclusion_rate'] - stats['threshold_impacts']['mean']['inclusion_rate']):.2f}%"
#                    )
#                }
#            else:
#                recommendation = {
#                    'should_change': False,
#                    'current_threshold': current,
#                    'recommended_threshold': recommended,
#                    'reason': "Current threshold is within acceptable range of optimal threshold"
#                }
#
#            return recommendation
#        
#        except Exception as e:
#            logging.error(f"Error getting threshold recommendation: {e}")
#            raise